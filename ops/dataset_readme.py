"""Maintain a bounded, generated section in each public dataset README."""
from datetime import datetime, timedelta, timezone
import html
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import quote

from common import PUBLIC, ROOT, atomic_json, read_json

START = '<!-- icechunker:global-attributes:start -->'
END = '<!-- icechunker:global-attributes:end -->'


def plain(value):
    """JSON-safe values, retaining arrays and making non-finite values explicit."""
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if hasattr(value, 'tolist'):
        return plain(value.tolist())
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f'Unsupported attribute type: {type(value).__name__}')


def file_order(key):
    dates = re.findall(r'(?<!\d)(\d{8})(?!\d)', Path(key).name)
    if not dates:
        raise ValueError(f'No dataset date in NetCDF filename: {key}')
    # Validate the filename date rather than ordering malformed names silently.
    datetime.strptime(dates[-1], '%Y%m%d')
    return dates[-1], key


def netcdf_attributes(url):
    """Read only the global header, never arrays or chunk offsets."""
    import fsspec
    options = {'headers': {'User-Agent': 'icechunker/1.0'}} if url.startswith(('http://', 'https://')) else {}
    with fsspec.open(url, 'rb', block_size=65536, cache_type='blockcache', **options).open() as source:
        magic = source.read(8)
        source.seek(0)
        if magic[:3] == b'CDF':
            from scipy.io import netcdf_file

            class GlobalHeader(netcdf_file):
                def _read_var_array(self):
                    pass  # stop after the global-attribute array

            if magic[3] not in (1, 2):
                raise ValueError('Unsupported NetCDF-3 header version')
            with GlobalHeader(source, mode='r', mmap=False) as header:
                return attributes(header._attributes)
        import h5py
        with h5py.File(source, 'r') as header:
            # netCDF-C hides these implementation attributes from ncattrs().
            return attributes({k: v for k, v in header.attrs.items()
                               if k not in ('_NCProperties', '_nc3_strict')})


def attributes(values):
    # netCDF-C exposes length-one attribute arrays as scalars, including NC_STRING.
    return {k: plain(v.reshape(-1)[0] if getattr(v, 'size', None) == 1 else v)
            for k, v in values.items()}


def public_url(cfg, key):
    return f'{PUBLIC}/{cfg["bucket"]}/' + quote(key, safe='/')


def prepare_file(cfg, name, state, completed, incoming, dry_run=False):
    if name == 'wrf_hi':
        return None  # PacIOOS owns this dataset's store and README.
    cached = read_json(state / 'readme-netcdf.json')
    if cached and completed.get(cached['key']) != cached['identity']:
        raise RuntimeError('README source copy identity changed or disappeared')
    if incoming:
        key = max(completed, key=file_order)
        if cached is None or file_order(key) > file_order(cached['key']):
            cached = dict(key=key, identity=completed[key],
                          attributes=netcdf_attributes(public_url(cfg, key)))
            if not dry_run:
                atomic_json(state / 'readme-netcdf.json', cached)
    return cached


def store_attributes(cfg, name, snapshot=None):
    if name == 'wrf_hi':
        raise ValueError('WRF store documentation is managed by PacIOOS')
    import icechunk
    import zarr
    settings = cfg['datasets'][name]
    url = public_url(cfg, settings['store_prefix'])
    repo = icechunk.Repository.open(icechunk.http_storage(url))
    if snapshot is None:
        snapshot = (repo.lookup_tag('v2.0') if name == 'roms_hiig_reanalysis'
                    else repo.lookup_branch('main'))
    session = repo.readonly_session(snapshot_id=snapshot)
    group = zarr.open_group(session.store, mode='r')
    return dict(url=url, snapshot=snapshot, attributes=plain(dict(group.attrs)))


def cell(value):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    value = html.escape(value)
    for character in '|\\`*_[]~':
        value = value.replace(character, f'&#{ord(character)};')
    return value.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '<br>')


def table(attributes):
    if not attributes:
        return 'No global attributes.\n'
    return '| Attribute | Value |\n|---|---|\n' + ''.join(
        f'| <code>{cell(key)}</code> | <code>{cell(attributes[key])}</code> |\n'
        for key in sorted(attributes))


def section(cfg, cached, store):
    text = START + '\n## Global metadata attributes\n\n'
    text += '### Published Icechunk dataset\n\n'
    if store is None:
        text += 'This dataset has no published Icechunk store.\n'
    else:
        text += f'Store: [{store["url"]}]({store["url"]}); snapshot <code>{cell(store["snapshot"])}</code>.\n\n'
        text += table(store['attributes'])
    url = public_url(cfg, cached['key'])
    text += '\n### Latest completed NetCDF copy\n\n'
    text += f'File: [{Path(cached["key"]).name}]({url}). Selected by filename date. '
    text += 'These are file attributes; other files may have different values.\n\n'
    return text + table(cached['attributes']) + '\n' + END


def replace_section(existing, generated, name):
    if not existing:
        existing = f'# PacIOOS {name}\n'
    starts, ends = existing.count(START), existing.count(END)
    if not starts and not ends:
        return existing + ('\n' if existing.endswith('\n') else '\n\n') + generated + '\n'
    if starts != 1 or ends != 1 or existing.index(END) < existing.index(START):
        raise ValueError('README has ambiguous or malformed icechunker metadata markers')
    begin = existing.index(START)
    finish = existing.index(END) + len(END)
    return existing[:begin] + generated + existing[finish:]


def s3_client(cfg):
    import boto3
    from botocore.config import Config
    sys.path.insert(0, str(ROOT / 'upload'))
    from source_coop_credentials import exchange, read_key
    credentials = exchange(read_key(Path(cfg['key_file'])), cfg['role_arn'])
    expiry = datetime.fromisoformat(credentials['Expiration'].replace('Z', '+00:00'))
    if expiry < datetime.now(timezone.utc) + timedelta(minutes=2):
        raise RuntimeError('Insufficient credential lifetime for README publication')
    return boto3.client('s3', endpoint_url=PUBLIC, region_name='us-east-1',
                        aws_access_key_id=credentials['AccessKeyId'],
                        aws_secret_access_key=credentials['SecretAccessKey'],
                        aws_session_token=credentials['SessionToken'],
                        config=Config(connect_timeout=30, read_timeout=120,
                                      retries={'max_attempts': 3},
                                      request_checksum_calculation='when_required',
                                      response_checksum_validation='when_required',
                                      s3={'addressing_style': 'path'}))


def write_readme(client, bucket, key, body, condition):
    # Source Cooperative needs multipart even for small objects (see upload/README.md).
    upload = client.create_multipart_upload(Bucket=bucket, Key=key,
                                           ContentType='text/markdown; charset=utf-8')
    upload_id = upload['UploadId']
    try:
        part = client.upload_part(Bucket=bucket, Key=key, UploadId=upload_id,
                                  PartNumber=1, Body=body)
        client.complete_multipart_upload(
            Bucket=bucket, Key=key, UploadId=upload_id,
            MultipartUpload={'Parts': [{'PartNumber': 1, 'ETag': part['ETag']}]}, **condition)
    except BaseException:
        # Completion may have succeeded despite a lost response; the next sync compares
        # remote content again. Never mask the original failure with abort cleanup errors.
        try:
            client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)
        except Exception:
            pass
        raise


def publish(cfg, name, generated, dry_run=False):
    """Read afresh on every attempt; conditionally write only this README key."""
    if name == 'wrf_hi':
        raise ValueError('WRF README publication is managed by PacIOOS')
    from botocore.exceptions import ClientError
    key = f'{cfg["prefix"]}/{name}/README.md'
    client = s3_client(cfg)
    try:
        try:
            response = client.get_object(Bucket=cfg['bucket'], Key=key)
        except ClientError as exc:
            if exc.response['Error']['Code'] != 'NoSuchKey':
                raise
            existing, etag = '', None
        else:
            body = response['Body']
            try:
                existing = body.read().decode('utf-8')
            finally:
                body.close()
            etag = response['ETag']
        candidate = replace_section(existing, generated, name)
        if candidate == existing:
            print(f'{name}: README metadata unchanged.', flush=True)
            return
        print(f'{name}: ' + ('Would update' if dry_run else 'Updating') + ' dataset README metadata.', flush=True)
        if not dry_run:
            condition = {'IfMatch': etag} if etag else {'IfNoneMatch': '*'}
            write_readme(client, cfg['bucket'], key, candidate.encode('utf-8'), condition)
    finally:
        client.close()


def reconcile(cfg, name, state, completed, incoming=(), dry_run=False, snapshot=None):
    """Called under the dataset lock, after copy/store validation (or for preview)."""
    if name == 'wrf_hi':
        print('WRF README is managed by PacIOOS; skipping documentation writes.', flush=True)
        return
    cached = prepare_file(cfg, name, state, completed, incoming, dry_run)
    if cached is None:
        print(f'{name}: README metadata waits for the next completed transfer.', flush=True)
        return
    pending_path = state / 'pending-readme.json'
    pending = read_json(pending_path)
    if snapshot is None and pending:
        snapshot = pending.get('snapshot')
    if not dry_run:
        atomic_json(pending_path, dict(snapshot=snapshot))
    store = store_attributes(cfg, name, snapshot)
    publish(cfg, name, section(cfg, cached, store), dry_run)
    if not dry_run:
        pending_path.unlink(missing_ok=True)
