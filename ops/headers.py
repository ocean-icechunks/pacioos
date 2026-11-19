"""Persist validated headers; routine updates never fill a historical cache from the network."""
from contextlib import contextmanager
import json
import os
import tempfile
from pathlib import Path

from common import RecoveryRequired, atomic_json, read_json


@contextmanager
def selected_runs(model, runs):
    original = model.list_runs
    if model.DATASET == 'roms_hiig':
        import pandas as pd
        model.list_runs = lambda: pd.DatetimeIndex(runs)
    else:
        model.list_runs = lambda: list(runs)
    try:
        yield
    finally:
        model.list_runs = original


def listed_runs(cfg, model, objects):
    import pandas as pd
    prefix = cfg['prefix'] + '/'
    keys = sorted(k[len(prefix):] for k in objects if k.startswith(prefix) and k.endswith('.nc'))
    if model.DATASET == 'roms_hiig':
        return sorted(pd.Timestamp(k.rsplit('_', 1)[1][:-3]).strftime('%Y-%m-%d') for k in keys)
    return sorted(keys, key=model.name_date)


def record_key(model, run):
    return model.key(run) if model.DATASET == 'roms_hiig' else run


def remember_reference(model, work, run):
    import numpy as np
    import pacioos_virtual as pv
    scanned = pv.scan_nc3(record_key(model, run))

    def plain(value):
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, bytes):
            return value.decode()
        raise TypeError(type(value).__name__)

    value = dict(coords={name: dict(dtype=array.dtype.str, values=array.tolist())
                         for name, array in scanned['coords'].items()},
                 mask_attrs=scanned.get('vars', {}).get('mask', {}).get('attrs', {}))
    atomic_json(work / 'reference.json', json.loads(json.dumps(value, default=plain)))


def load_reference(work):
    import numpy as np
    value = read_json(work / 'reference.json')
    if value is None:
        raise RuntimeError('Header reference cache is missing. Run icechunker verify --scope full once to initialize it.')
    return dict(coords={name: np.asarray(item['values'], dtype=item['dtype'])
                        for name, item in value['coords'].items()},
                vars={'mask': {'attrs': value['mask_attrs']}})


def adopt_seed(cfg, model, work, objects):
    """Reuse previously validated public metadata without reading historical NetCDFs."""
    import gzip
    import hashlib
    import shutil
    seed = Path(cfg['state_dir']) / 'seeds/headers' / model.DATASET
    provenance = read_json(seed / 'provenance.json')
    if provenance is None or not (seed / 'scan.jsonl.gz').exists():
        return False
    if (provenance['bucket'], provenance['prefix']) != (cfg['bucket'], cfg['prefix']):
        return False
    for key, identity in provenance['copy_identities'].items():
        if {'data': objects.get(key), 'sidecar': objects.get(key + '.md5')} != identity:
            raise RuntimeError('Cached header seed does not match the current source-copy identities; '
                               'run icechunker verify --scope full instead')
    approved = read_json(seed / 'approved-runs.json')
    reference = read_json(seed / 'reference.json')
    if approved is None or reference is None:
        raise RuntimeError('Header seed is incomplete')
    fd, temporary = tempfile.mkstemp(prefix='seed-', suffix='.jsonl', dir=work)
    try:
        digest = hashlib.sha256()
        with os.fdopen(fd, 'wb') as target:
            current = work / 'scan.jsonl'
            if current.exists():
                with current.open('rb') as source:
                    shutil.copyfileobj(source, target)
            with gzip.open(seed / 'scan.jsonl.gz', 'rb') as source:
                for block in iter(lambda: source.read(1 << 20), b''):
                    digest.update(block)
                    target.write(block)
        if digest.hexdigest() != provenance['scan_sha256']:
            raise RuntimeError('Header seed checksum differs')
        os.replace(temporary, work / 'scan.jsonl')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    atomic_json(work / 'reference.json', reference)
    previous = set(read_json(work / 'approved-runs.json', []))
    atomic_json(work / 'approved-runs.json', sorted(previous | set(approved)))
    atomic_json(work / 'seed-adopted.json', dict(source=str(seed), historical_files_read=0))
    (seed / 'scan.jsonl.gz').unlink()
    print(f'Loaded {len(approved)} previously validated cached headers; '
          'no historical NetCDF files were read. This is not a new full-verification result.', flush=True)
    return True


def prepare(cfg, model, bs, work, objects, incoming, full=False):
    runs = listed_runs(cfg, model, objects)
    if not runs:
        raise RuntimeError('No completed source runs found')
    records = bs.load_scan(work) if (work / 'scan.jsonl').exists() else {}
    approved = set(read_json(work / 'approved-runs.json', []))
    if full:
        print(f'Full verification: refreshing all {len(runs)} source headers.', flush=True)
        with selected_runs(model, runs):
            bs.scan(work, cfg['scan_processes'], force=True)
            # load_scan intentionally preserves older successes over later errors for
            # resumable builds. A forced audit must instead fail on its latest read error.
            latest = {}
            for line in (work / 'scan.jsonl').read_text().splitlines():
                record = json.loads(line)
                latest[record.get('day', record['key'])] = record
            if any('error' in latest[run] for run in runs):
                raise RuntimeError('Full header refresh failed; cached older successes do not count as verification')
            try:
                bs.check(work)
            except SystemExit as exc:
                raise RuntimeError(str(exc)) from exc
        remember_reference(model, work, runs[0])
        fd, temporary = tempfile.mkstemp(prefix='headers-', suffix='.jsonl', dir=work)
        try:
            with os.fdopen(fd, 'w') as stream:
                for run in runs:
                    stream.write(json.dumps(latest[run]) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, work / 'scan.jsonl')
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        atomic_json(work / 'approved-runs.json', runs)
        return runs
    new_runs = [run for run in runs if cfg['prefix'] + '/' + record_key(model, run) in incoming]
    missing = [run for run in runs if run not in new_runs and
               (run not in approved or run not in records or 'error' in records[run])]
    if missing and adopt_seed(cfg, model, work, objects):
        records = bs.load_scan(work)
        approved = set(read_json(work / 'approved-runs.json', []))
        missing = [run for run in missing if run not in approved or run not in records or 'error' in records[run]]
    if missing:
        raise RecoveryRequired(f'{len(missing)} historical headers lack a validated cache. '
                               'Normal sync will not scan the archive. Run icechunker verify --scope full once.')
    load_reference(work)  # require a cached grid; no old source file is reopened for planning
    reference = next((run for run in runs if run in approved and run in records), None)
    if reference is None:
        raise RecoveryRequired('No cached schema baseline. Run icechunker verify --scope full once.')
    if new_runs:
        print(f'Routine verification: scanning {len(new_runs)} new/pending headers; '
              f'reusing {len(runs) - len(new_runs)} historical cached headers.', flush=True)
        with selected_runs(model, new_runs):
            bs.scan(work, cfg['scan_processes'])
        # The reference is a cached row, not another source read.
        with selected_runs(model, sorted(set([reference, *new_runs]))):
            try:
                bs.check(work)
            except SystemExit as exc:
                raise RuntimeError(str(exc)) from exc
        atomic_json(work / 'approved-runs.json', sorted(approved | set(new_runs)))
    else:
        print('No new source headers to scan; using validated cached metadata.', flush=True)
    return runs


def cached_plan(bs, model, work, runs):
    reference = load_reference(work)
    records = bs.load_scan(work)
    if model.DATASET == 'roms_hiig':
        main, ssh, fetched = model.load_metadata()
        attrs = model.variable_attrs(main, ssh, reference['vars']['mask']['attrs'])
        dataset = model.build_dataset(bs._scans_for(records, runs, reference), attrs, main)
    else:
        erddap, fetched = model.load_metadata()
        dataset = model.build_dataset(bs.scans_from(records, runs, reference),
                                      model.variable_attrs(erddap), erddap, fetched)
    return dataset, runs, fetched
