"""The ROMS Hawaiʻi reanalysis v2.0 virtual store: everything the notebooks and the build share.

Issue #11. Decisions (Eli Holmes, 2026-11-14):

- one depth plane per chunk, ``(1, 1, 195, 295)``: references cut inside each uncompressed
  HDF5 chunk (the HYCOM trick);
- metadata from PacIOOS's ERDDAP record of the dataset, saved in ``erddap_metadata.json`` so the
  build does not depend on ERDDAP being up; the title drops ERDDAP's ": 3-D Variables", because
  this store also holds ``zeta``;
- one group (the root) with all five variables.

The generic reference code (header scans, depth-plane manifests, repository config) is in
``../pacioos_virtual.py``; this module adds what is specific to the reanalysis.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from xarray.backends.zarr import FillValueCoder

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import pacioos_virtual as pv  # noqa: E402

URL_PREFIX = pv.URL_PREFIX                 # https://data.source.coop/ocean-icechunks/pacioos/
DATASET = 'roms_hiig_reanalysis'
VERSION = 'v2.0'                           # in the folder name, not in the files (#2)
FILE_SIZE = 267_070_520                    # every one of the 4,380 copies
ALL_DAYS = pd.date_range('2009-01-01', '2020-12-28', freq='D')
STEPS = pd.date_range('2009-01-01', '2020-12-28 21:00', freq='3h')    # 35,040, as ERDDAP
SCIENCE = ['temp', 'salt', 'u', 'v', 'zeta']
PLANE = 195 * 295 * 4                      # one (lat, lon) float32 plane, 230,100 bytes
TIME_PER_MANIFEST = 2920                   # one year of 3-hourly steps per manifest

ERDDAP = 'https://pae-paha.pacioos.hawaii.edu/erddap'
ERDDAP_IDS = ('roms_hiig_reanalysis', 'roms_hiig_reanalysis_ssh')     # temp/salt/u/v, zeta
METADATA_FILE = HERE / 'erddap_metadata.json'

# Attributes that only drive ERDDAP's own displays and bookkeeping, not the data.
ERDDAP_ONLY = {'_ChunkSizes', '_CoordinateAxisType', '_CoordinateZisPositive', 'actual_range',
               'colorBarMaximum', 'colorBarMinimum', 'colorBarPalette', 'colorBarScale',
               'ioos_category', 'time_origin'}
GLOBAL_ERDDAP_ONLY = {'cdm_data_type', 'defaultGraphQuery', 'drawLandMask', 'sourceUrl',
                      'infoUrl', 'Easternmost_Easting', 'Westernmost_Easting',
                      'Northernmost_Northing', 'Southernmost_Northing',
                      'time_coverage_start', 'time_coverage_end'}   # coverage: from the store
TITLE = 'Regional Ocean Modeling System (ROMS): Main Hawaiian Islands: Reanalysis'


def key(day) -> str:
    """Object key under URL_PREFIX of one day's file."""
    d = pd.Timestamp(day)
    return f'{DATASET}/netcdf/{VERSION}/{d:%Y}/hiig_his_zlevel_{d:%Y%m%d}.nc'


# ------------------------------------------------------------------ ERDDAP metadata

def fetch_erddap_rows(dataset_id: str, timeout: int = 60) -> list[list[str]]:
    """The attribute rows of one ERDDAP dataset, as ERDDAP's info service gives them."""
    import fsspec
    raw = fsspec.filesystem('https', client_kwargs={'timeout': None}).cat(
        f'{ERDDAP}/info/{dataset_id}/index.json')
    rows = json.loads(raw)['table']['rows']
    return [r for r in rows if r[0] == 'attribute']


def save_erddap_metadata(path: Path = METADATA_FILE) -> None:
    """Refresh the saved copy from ERDDAP. Review the diff before committing it."""
    snapshot = {
        'fetched': pd.Timestamp.now('UTC').strftime('%Y-%m-%dT%H:%M:%SZ'),
        'source': f'{ERDDAP}/info/<id>/index.json',
        'datasets': {i: fetch_erddap_rows(i) for i in ERDDAP_IDS},
    }
    # One attribute row per line, so a refresh shows up as a readable diff.
    lines = ['{', f' "fetched": {json.dumps(snapshot["fetched"])},',
             f' "source": {json.dumps(snapshot["source"])},', ' "datasets": {']
    for n, (i, rows) in enumerate(snapshot['datasets'].items()):
        lines.append(f'  {json.dumps(i)}: [')
        lines += [f'   {json.dumps(r, ensure_ascii=False)}' + (',' if k < len(rows) - 1 else '')
                  for k, r in enumerate(rows)]
        lines.append('  ]' + (',' if n < len(snapshot['datasets']) - 1 else ''))
    lines += [' }', '}']
    path.write_text('\n'.join(lines) + '\n')


def _parse(rows) -> dict:
    out = {}
    for _row_type, var, attr, dtype, value in rows:
        if dtype in ('float', 'double') and ',' not in value:
            value = np.float32(value) if dtype == 'float' else float(value)
        elif dtype in ('int', 'short', 'byte') and ',' not in value:
            value = int(value)
        out.setdefault(var, {})[attr] = value
    return out


def load_metadata(path: Path = METADATA_FILE) -> tuple[dict, dict, str]:
    """(main, ssh, fetched): the saved ERDDAP attributes, {variable: {attribute: value}}."""
    snap = json.loads(Path(path).read_text())
    main = _parse(snap['datasets'][ERDDAP_IDS[0]])
    main['_fetched'] = snap['fetched']           # for metadata_source; not an attribute
    return main, _parse(snap['datasets'][ERDDAP_IDS[1]]), snap['fetched']


def compare_with_live_erddap(path: Path = METADATA_FILE) -> pd.DataFrame | None:
    """Differences between the saved copy and ERDDAP now, or None if ERDDAP does not answer.

    Never raises on a network error: ERDDAP restarts now and then (it answered 503, then
    "Currently unknown datasetID", for about a minute on 2026-11-14) and the build must not
    depend on it.
    """
    snap = json.loads(Path(path).read_text())
    diffs = []
    for i in ERDDAP_IDS:
        try:
            live = _parse(fetch_erddap_rows(i))
        except Exception as exc:                                   # noqa: BLE001
            print(f'ERDDAP did not answer for {i} ({type(exc).__name__}); using the saved copy')
            return None
        saved = _parse(snap['datasets'][i])
        for var in sorted(set(saved) | set(live)):
            for attr in sorted(set(saved.get(var, {})) | set(live.get(var, {}))):
                a, b = saved.get(var, {}).get(attr), live.get(var, {}).get(attr)
                if str(a) != str(b):
                    diffs.append({'dataset': i, 'variable': var, 'attribute': attr,
                                  'saved': a, 'live': b})
    return pd.DataFrame(diffs, columns=['dataset', 'variable', 'attribute', 'saved', 'live'])


def variable_attrs(main: dict, ssh: dict, file_mask_attrs: dict) -> dict:
    """{store variable: attrs}. ERDDAP names latitude/longitude; the store keeps lat/lon."""
    attrs = {}
    for name in SCIENCE:
        src = (ssh if name == 'zeta' else main)[name]
        attrs[name] = {k: src[k] for k in ('long_name', 'standard_name', 'units', '_FillValue')}
    for store_name, erddap_name in [('lat', 'latitude'), ('lon', 'longitude'), ('depth', 'depth'),
                                    ('time', 'time')]:
        attrs[store_name] = {k: v for k, v in main[erddap_name].items()
                             if k not in ERDDAP_ONLY and not (store_name == 'time' and k == 'units')}
    attrs['mask'] = dict(file_mask_attrs)      # not in ERDDAP; the file's own
    return attrs


def metadata_source(fetched: str) -> str:
    """The store's `metadata_source` attribute: where its attributes came from."""
    return (f'Variable and global attributes from PacIOOS ERDDAP datasets {ERDDAP_IDS[0]} and '
            f'{ERDDAP_IDS[1]} ({ERDDAP}/info/{ERDDAP_IDS[0]}/index.html), saved {fetched} in '
            'stores/roms_hiig_reanalysis/erddap_metadata.json of '
            'https://github.com/ocean-icechunks/pacioos. The NetCDF files carry only author, '
            'history and title ("Zlevel Model Data"), no fill value, temp units "ppt" and no salt '
            'units. mask is the files\' own. No data values were changed.')


def global_attrs(main: dict, time_index, now=None) -> dict:
    """Global attributes for a store covering `time_index`."""
    now = pd.Timestamp(now or pd.Timestamp.now('UTC'))
    attrs = {k: v for k, v in main['NC_GLOBAL'].items() if k not in GLOBAL_ERDDAP_ONLY}
    attrs.update({
        'title': TITLE,
        'time_coverage_start': f'{time_index[0]:%Y-%m-%dT%H:%M:%SZ}',
        'time_coverage_end': f'{time_index[-1]:%Y-%m-%dT%H:%M:%SZ}',
        'source_files': URL_PREFIX + f'{DATASET}/netcdf/{VERSION}/',
        'metadata_source': metadata_source(main.get('_fetched', 'see erddap_metadata.json')),
        'history': main['NC_GLOBAL']['history'] + '\n'
                   + f'{now:%Y-%m-%dT%H:%M:%SZ} Virtual Icechunk store over unchanged copies of '
                   'the v2.0 NetCDF files; metadata from PacIOOS ERDDAP, no data values changed.',
    })
    return attrs


# ------------------------------------------------------------------ the dataset

def build_dataset(scans: list[dict], var_attrs: dict, main: dict) -> xr.Dataset:
    """One virtual dataset over `scans` (pv.scan_h5 results, oldest first, contiguous)."""
    best = pv.best_assignment(scans, '3h')
    assert (best['run'] >= 0).all(), 'gap in the time axis'
    fill = var_attrs['temp']['_FillValue']
    data = {}
    for name in SCIENCE:
        dims = ('time', 'depth', 'lat', 'lon') if name != 'zeta' else ('time', 'lat', 'lon')
        # For Zarr v3, xarray keeps _FillValue base64-encoded and refuses a plain float on open.
        attrs = dict(var_attrs[name], _FillValue=FillValueCoder.encode(fill, np.dtype('f4')))
        data[name] = pv.manifest_variable(name, scans, best, dims, attrs, fill_value=fill)
    c = scans[0]['coords']
    ds = xr.Dataset(data, coords={
        'time': ('time', best.index.values, var_attrs['time']),
        'depth': ('depth', c['depth'], var_attrs['depth']),
        'lat': ('lat', c['lat'], var_attrs['lat']),
        'lon': ('lon', c['lon'], var_attrs['lon']),
    })
    ds['mask'] = (('lat', 'lon'), c['mask'], var_attrs['mask'])
    ds.attrs = global_attrs(main, best.index)
    # The files' own time units, as float64, the whole axis in one chunk.
    ds['time'].encoding = {'units': 'hours since 2000-01-01', 'dtype': 'float64',
                           'chunks': (len(best),)}
    return ds


def repository_config():
    return pv.repository_config(time_chunks_per_manifest=TIME_PER_MANIFEST)


def open_store(storage, ref: str = 'main', chunks=None, **kw) -> xr.Dataset:
    """Open a store as a reader: containers from the saved config, anonymous HTTP to each.

    `ref` is a branch or a tag ('v2.0'). Pass chunks=None (the default here) for point series:
    with chunks={} dask runs one task per 230 KB chunk and its thread pool, not Zarr's
    async.concurrency, limits the reads (120 s against 5 s for a year, 2026-11-13).
    """
    import icechunk
    repo = icechunk.Repository.open(storage)
    auth = {p: icechunk.credentials.HttpAccess for p in repo.config.virtual_chunk_containers or []}
    repo = repo.reopen(authorize_virtual_chunk_access=auth)
    tags = set(repo.list_tags())
    session = repo.readonly_session(tag=ref) if ref in tags else repo.readonly_session(ref)
    return xr.open_zarr(session.store, consolidated=False, chunks=chunks, **kw)
