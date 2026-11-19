"""Local upload, byte verification, incremental publication and restart recovery."""
from __future__ import annotations

from datetime import datetime, timezone
import importlib
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

from common import PUBLIC, ROOT, atomic_json, read_json


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def get(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'pacioos-sync/1.0'})
    return urllib.request.urlopen(request, timeout=120)


def inventory(cfg, name):
    """Paginated public inventory: identity includes size, ETag and modification time."""
    namespace = {'s': 'http://s3.amazonaws.com/doc/2006-03-01/'}
    token, result = None, {}
    while True:
        query = {'list-type': '2', 'prefix': f'{cfg["prefix"]}/{name}/netcdf/'}
        if token:
            query['continuation-token'] = token
        with get(f'{PUBLIC}/{cfg["bucket"]}?' + urllib.parse.urlencode(query)) as response:
            root = ET.fromstring(response.read())
        for item in root.findall('s:Contents', namespace):
            key = item.findtext('s:Key', namespaces=namespace)
            result[key] = dict(size=int(item.findtext('s:Size', namespaces=namespace)),
                               etag=item.findtext('s:ETag', namespaces=namespace),
                               modified=item.findtext('s:LastModified', namespaces=namespace))
        if root.findtext('s:IsTruncated', namespaces=namespace) != 'true':
            break
        next_token = root.findtext('s:NextContinuationToken', namespaces=namespace)
        if not next_token or next_token == token:
            raise RuntimeError('Public listing did not supply a new continuation token')
        token = next_token
    return result


def object_url(cfg, key):
    return f'{PUBLIC}/{cfg["bucket"]}/' + urllib.parse.quote(key, safe='/')


def copy_identity(objects, key):
    if key not in objects or key + '.md5' not in objects:
        raise RuntimeError(f'Copy or checksum sidecar missing: {key}')
    return dict(data=objects[key], sidecar=objects[key + '.md5'])


def verify_copies(cfg, state, objects, keys):
    """Verify only selected copies not already recorded with the same immutable identity."""
    import hashlib
    ledger_path = state / 'verified-copies.json'
    ledger = read_json(ledger_path, {})
    for key in sorted(set(keys)):
        identity = copy_identity(objects, key)
        previous = ledger.get(key)
        if previous:
            if previous['identity'] != identity:
                raise RuntimeError(f'Previously verified immutable object changed: {key}')
            continue
        with get(object_url(cfg, key + '.md5')) as response:
            checksum = response.read(4096).decode().split()[0]
        if not re.fullmatch('[a-fA-F0-9]{32}', checksum):
            raise RuntimeError(f'Invalid MD5 sidecar: {key}')
        digest, count = hashlib.md5(), 0
        with get(object_url(cfg, key)) as response:
            for block in iter(lambda: response.read(8 << 20), b''):
                count += len(block)
                digest.update(block)
        if count != objects[key]['size'] or digest.hexdigest().lower() != checksum.lower():
            raise RuntimeError(f'Public copy fails size/MD5 verification: {key}')
        ledger[key] = dict(identity=identity, md5=checksum.lower(), verified=utcnow())
        atomic_json(ledger_path, ledger)
        print(f'Copy verified by public download: {key} ({count} bytes)', flush=True)
    return ledger


def upload(cfg, name, dry_run):
    """Bound batches by credential lifetime, preserving the existing immutable uploader."""
    sys.path.insert(0, str(ROOT / 'upload'))
    from source_coop_credentials import exchange, read_key
    uploaded = set()
    for batch in range(cfg['max_upload_batches']):
        credentials = exchange(read_key(Path(cfg['key_file'])), cfg['role_arn'])
        expiry = datetime.fromisoformat(credentials['Expiration'].replace('Z', '+00:00'))
        hours = (expiry - datetime.now(timezone.utc)).total_seconds() / 3600 - 0.5
        if hours <= 0:
            raise RuntimeError('Temporary credentials have insufficient time remaining')
        env = os.environ.copy()
        for key in ('BASH_ENV', 'ENV', 'SHELLOPTS', 'BASHOPTS'):
            env.pop(key, None)
        env.update(AWS_ACCESS_KEY_ID=credentials['AccessKeyId'],
                   AWS_SECRET_ACCESS_KEY=credentials['SecretAccessKey'],
                   AWS_SESSION_TOKEN=credentials['SessionToken'], AWS_EC2_METADATA_DISABLED='true',
                   RCLONE=cfg['rclone'], PARALLEL=str(cfg['upload_parallel']),
                   MIN_AGE_MINUTES=str(cfg['minimum_age_minutes']), MAX_HOURS=str(min(hours, 0.49)),
                   DEST=f'{cfg["bucket"]}/{cfg["prefix"]}', VERSION='')
        command = ['bash', str(ROOT / 'upload/upload_to_source_coop.sh')]
        if dry_run:
            command.append('--dry-run')
        command.append(f'{name}={cfg["datasets"][name]["source_dir"]}')
        summary = None
        print(f'{name}: upload batch {batch + 1}', flush=True)
        with subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True) as proc:
            for line in proc.stdout:
                print(line, end='', flush=True)
                match = re.match(r'^OK\s+[^/]+/(.+?)  size=', line)
                if match:
                    version = 'v2.0/' if name == 'roms_hiig_reanalysis' else ''
                    uploaded.add(f'{cfg["prefix"]}/{name}/netcdf/{version}{match.group(1)}')
                match = re.search(r': (\d+) uploaded, (\d+) failed, (\d+) left for the next run, (\d+) changed', line)
                if match:
                    summary = tuple(map(int, match.groups()))
            code = proc.wait()
        if code:
            raise RuntimeError(f'Uploader exited {code}; no store update will run for {name}')
        if summary is None:
            raise RuntimeError('Uploader produced no completion summary')
        if summary[1] or summary[3]:
            raise RuntimeError('Upload failures or changed originals require review')
        if dry_run or summary[2] == 0:
            return uploaded
    raise RuntimeError('Upload batch limit reached with deferred files; rerun to continue')


def modules(cfg, name):
    os.environ.update(PACIOOS_BUCKET=cfg['bucket'], PACIOOS_PREFIX=cfg['prefix'],
                      SOURCE_COOP_AUTH='api-key', SOURCE_COOP_API_KEY_FILE=cfg['key_file'],
                      SOURCE_COOP_ROLE_ARN=cfg['role_arn'])
    sys.path[:0] = [str(ROOT / 'stores' / name), str(ROOT / 'stores')]
    bs = importlib.import_module('build_store')
    model = importlib.import_module('forecast_store' if name == 'roms_hiig' else 'ww3_store')
    return bs, model


def plan_for(bs, model, work, source_runs=None):
    """Reconstruct an interrupted job's exact input selection from persistent headers."""
    from headers import cached_plan
    runs = source_runs if source_runs is not None else sorted(bs.load_scan(work))
    return cached_plan(bs, model, work, runs)


def manifest_keys(cfg, planned, changed):
    import numpy as np
    import best_series_update as bsu
    root = f'{PUBLIC}/{cfg["bucket"]}/'
    keys = set()
    for name in bsu.gridded(planned):
        for value in np.unique(planned[name].data.manifest._paths[changed]):
            value = str(value)
            if value:
                if not value.startswith(root + cfg['prefix'] + '/'):
                    raise RuntimeError('Plan references a location outside the configured source root')
                keys.add(urllib.parse.unquote(value[len(root):]))
    return keys


def audit_inventory(cfg, name, state, objects, bs, work):
    """Archive-wide inventory check, independent of science-data sampling."""
    live = {key for key in objects if key.endswith('.nc')}
    for key in live:
        copy_identity(objects, key)
    records = bs.load_scan(work)
    scanned = {cfg['prefix'] + '/' + record['key'] for record in records.values() if 'error' not in record}
    if scanned != live:
        raise RuntimeError('Historical header cache and source-copy inventory differ')
    ledger = read_json(state / 'verified-copies.json', {})
    baseline = read_json(state / 'baseline-copies.json', {})
    for key, identity in baseline.items():
        if copy_identity(objects, key) != identity:
            raise RuntimeError(f'Previously published copy identity changed: {key}')
    for key, record in ledger.items():
        if copy_identity(objects, key) != record['identity']:
            raise RuntimeError(f'Immutable copy identity changed: {key}')
    print(f'Full inventory audit: {len(live)} copies, {len(ledger)} recorded MD5 downloads; '
          'older published copies are not retroactively marked byte-verified.', flush=True)


def finish_validation(cfg, state, storage, plan, snapshot, scope, now, only_sources=None):
    from validation import verify_snapshot
    result = verify_snapshot(storage, plan, snapshot, scope, cfg, now, only_sources=only_sources)
    result['validated_at'] = utcnow()
    atomic_json(state / f'last-success-{scope}.json', result)
    failure = state / f'last-failure-verify-{scope}.json'
    failure.unlink(missing_ok=True)
    return result


def recover(cfg, state, repo, storage, bs, model, work):
    """Resolve a commit/validation interruption before allowing any further write."""
    pending_path = state / 'pending-update.json'
    pending = read_json(pending_path)
    if pending is None:
        return
    snapshot = pending.get('snapshot')
    if snapshot is None:
        if repo.lookup_branch('main') == pending['before']:
            pending_path.unlink()  # the prepared transaction never committed
            return
        for i, ancestor in enumerate(repo.ancestry(branch='main')):
            if pending['token'] in ancestor.message:
                snapshot = ancestor.id
                break
            if i >= 1000:
                break
        if snapshot is None:
            raise RuntimeError('Branch moved after an interrupted commit; cannot identify it safely')
    old_plan = plan_for(bs, model, work, pending['source_runs'])[0]
    print(f'Resuming validation of interrupted snapshot {snapshot}', flush=True)
    finish_validation(cfg, state, storage, old_plan, snapshot, 'recent', pending['started'],
                      only_sources=pending.get('new_source_urls'))
    pending_path.unlink()


def complete_sync(cfg, name, state, completed, incoming, snapshot=None):
    """Acknowledge validated data separately from retryable README publication."""
    from dataset_readme import prepare_file, reconcile
    prepare_file(cfg, name, state, completed, incoming)
    atomic_json(state / 'pending-readme.json', dict(snapshot=snapshot))
    atomic_json(state / 'known-copies.json', completed)
    reconcile(cfg, name, state, completed, snapshot=snapshot)


def process(cfg, name, state, action, scope, dry_run):
    started = utcnow()
    print(f'{started} {name}: {action} ({scope})' + (' DRY RUN' if dry_run else ''), flush=True)
    if action == 'verify' and not cfg['datasets'][name]['update_store']:
        print(f'{name}: no automatic store verifier configured; skipping store verification.', flush=True)
        return
    baseline_path = state / 'baseline-copies.json'
    baseline = read_json(baseline_path)
    if action == 'sync' and not dry_run and baseline is None:
        previous_objects = inventory(cfg, name)
        baseline = {key: copy_identity(previous_objects, key) for key in previous_objects
                    if key.endswith('.nc') and key + '.md5' in previous_objects}
        atomic_json(baseline_path, baseline)
    uploaded = upload(cfg, name, dry_run) if action == 'sync' else set()
    objects = inventory(cfg, name)
    completed = {key: copy_identity(objects, key) for key in objects
                 if key.endswith('.nc') and key + '.md5' in objects}
    known = read_json(state / 'known-copies.json', baseline if baseline is not None else completed)
    # Acknowledge incoming copies only after publication/validation. This also recovers a
    # crash after the MD5 ledger was written but before the Icechunk update committed.
    incoming = uploaded | (set(completed) - set(known)) if action == 'sync' else set()
    if action == 'sync' and not incoming and not (state / 'pending-update.json').exists():
        from dataset_readme import reconcile
        reconcile(cfg, name, state, completed, dry_run=dry_run)
        print('No new or pending transfers: skipping source-header scans, data verification '
              'and Icechunk writes. Historical verification is a separate full job.', flush=True)
        if not dry_run:
            atomic_json(state / 'last-success-sync.json', dict(time=utcnow(), no_new_transfers=True))
        return
    if not cfg['datasets'][name]['update_store']:
        if not dry_run:
            verify_copies(cfg, state, objects, incoming)
            complete_sync(cfg, name, state, completed, incoming)
            atomic_json(state / 'last-success-upload.json', dict(time=utcnow(), uploaded=sorted(incoming)))
        else:
            from dataset_readme import reconcile
            reconcile(cfg, name, state, completed, incoming, dry_run=True)
        return
    import icechunk
    import numpy as np
    bs, model = modules(cfg, name)
    import best_series_update as bsu
    work = state / 'headers'
    work.mkdir(exist_ok=True)
    from headers import prepare
    runs = prepare(cfg, model, bs, work, objects, incoming, full=action == 'verify' and scope == 'full')
    planned, runs, _ = plan_for(bs, model, work, runs)
    url = f'{PUBLIC}/{cfg["bucket"]}/{cfg["datasets"][name]["store_prefix"]}'
    public_storage = icechunk.http_storage(url)
    if action == 'verify':
        repo = icechunk.Repository.open(public_storage)
        snapshot = repo.lookup_branch('main')
        if scope == 'full':
            audit_inventory(cfg, name, state, objects, bs, work)
        finish_validation(cfg, state, public_storage, planned, snapshot, scope, started)
        return
    from icechunk_utils import open_source_icechunk_repo
    import pacioos_virtual as pv
    repo, _, _, _ = open_source_icechunk_repo(
        cfg['bucket'], cfg['datasets'][name]['store_prefix'], min_minutes_left=20,
        create_if_missing=False, verbose=False)
    if repo is None:
        raise RuntimeError('Insufficient credential lifetime for a store update')
    repo = repo.reopen(authorize_virtual_chunk_access=pv.reader_authorization())
    if not dry_run:
        recover(cfg, state, repo, public_storage, bs, model, work)
    before = repo.lookup_branch('main')
    changes = bsu.plan_changes(bsu.read_state(repo), planned)
    print(f'Store diff: {changes["appended"]} appended, {changes["repointed"]} re-pointed', flush=True)
    if dry_run:
        from dataset_readme import reconcile
        reconcile(cfg, name, state, completed, incoming, dry_run=True)
        print('Dry run complete; no remote objects or snapshots were written.', flush=True)
        return
    # Reject stale plans before making a commit. This also bounds the recent validation window.
    from validation import scope_indices
    scope_indices(planned, 'recent', started, cfg['verify_lookback_days'], cfg['max_run_age_hours'])
    verify_copies(cfg, state, objects, incoming)
    # Previously published copies remain a metadata baseline; don't re-download them just
    # because the best-series calculation uses their cached headers.
    for key in manifest_keys(cfg, planned, changes['changed']):
        copy_identity(objects, key)
    new_source_urls = [object_url(cfg, key) for key in sorted(incoming)]
    snapshot = before
    if len(changes['changed']):
        token = 'pacioos-job-' + uuid.uuid4().hex
        pending = dict(token=token, before=before, source_runs=list(runs), started=started,
                       new_source_urls=new_source_urls,
                       historical_changes_deferred=int((planned.time.values[changes['changed']] <
                           np.datetime64(started[:19]) - np.timedelta64(cfg['verify_lookback_days'], 'D')).sum()))
        atomic_json(state / 'pending-update.json', pending)
        snapshot = bsu.apply_update(repo, planned, changes,
                                    f'{token}: {changes["appended"]} appended, {changes["repointed"]} re-pointed')
        pending['snapshot'] = snapshot
        atomic_json(state / 'pending-update.json', pending)
        atomic_json(state / 'last-update.json', pending)
        print(f'Committed {snapshot}', flush=True)
    finish_validation(cfg, state, public_storage, planned, snapshot, 'recent', started,
                      only_sources=new_source_urls)
    (state / 'pending-update.json').unlink(missing_ok=True)
    complete_sync(cfg, name, state, completed, incoming, snapshot)
    atomic_json(state / 'last-success-sync.json', dict(time=utcnow(), snapshot=snapshot))


def check_setup(cfg):
    """Local-only checks: no credential exchange, network writes, or job execution."""
    import importlib
    for name in ('icechunk', 'virtualizarr', 'zarr', 'netCDF4', 'h5py', 'scipy', 'boto3'):
        importlib.import_module(name)
    sys.path.insert(0, str(ROOT / 'upload'))
    from source_coop_credentials import read_key
    read_key(Path(cfg['key_file']))
    if not os.access(cfg['rclone'], os.X_OK):
        raise ValueError('Configured rclone is not executable')
    import stat
    for name in ('config_file', 'key_file'):
        target = Path(cfg[name])
        if target.stat().st_uid != os.getuid() or stat.S_IMODE(target.stat().st_mode) & 0o077:
            raise ValueError(f'{name} must be private and owned by the job user')
    if stat.S_IMODE(Path(cfg['key_file']).parent.stat().st_mode) & 0o077:
        raise ValueError('Key directory must be private (chmod 700)')
    for folder in ('state', 'logs', '.runtime/tmp'):
        target = Path(cfg['install_root']) / folder
        if not target.is_dir() or not os.access(target, os.R_OK | os.W_OK | os.X_OK):
            raise ValueError(f'{folder}: directory must be accessible and writable')
    for name, settings in cfg['datasets'].items():
        if not Path(settings['source_dir']).is_dir() or not os.access(settings['source_dir'], os.R_OK | os.X_OK):
            raise ValueError(f'{name}: source_dir is not a directory')
    print('Local configuration, key permissions/format, imports and source folders passed.')
    print('No credentials were exchanged and no sync or verification was run.')
