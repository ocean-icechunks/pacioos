"""The ROMS Hawaiʻi forecast virtual store, best series: what the notebooks and the build share.

Issue #10. Decisions (Eli Holmes, 2026-11-14), the same as the reanalysis store (#11):

- one depth plane per chunk, ``(1, 1, 195, 295)``: references cut inside each NetCDF-3 record
  slab (the HYCOM trick);
- metadata from PacIOOS's ERDDAP record of the dataset (``roms_hiig`` and ``roms_hiig_ssh``),
  saved in ``erddap_metadata.json`` so the build does not depend on ERDDAP being up; the title
  ends ": Forecast" instead of ERDDAP's ": 3-D Variables", because the store also holds
  ``zeta``;
- one group (the root) with all five variables, native ``lat``/``lon`` names;
- the THREDDS FMRC "best" rule: for each valid time, the newest run that has it;
- **a regular 3-hourly axis**: a time that no run covers stays on the axis with no reference,
  so it reads as NaN and its ``forecast_reference_time`` is NaT (none exist yet).

The generic reference code (header scans, the best rule, depth-plane manifests, repository
config) is in ``../pacioos_virtual.py``; this module adds what is specific to the forecast.
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
DATASET = 'roms_hiig'
SCIENCE = ['temp', 'salt', 'u', 'v', 'zeta']
STEPS_PER_RUN = 57                         # 00Z on the run's day to 00Z seven days later
PLANE = 195 * 295 * 4                      # one (lat, lon) float32 plane, 230,100 bytes
RECSIZE = 33_364_504                       # one NetCDF-3 record: time + 5 variables, one step
TIME_PER_MANIFEST = 2920                   # one year of 3-hourly steps per manifest
TIME_UNITS = 'hours since 2000-01-01'      # the files' own
# Land in every file holds 9.99e10, declared as missing_value (float32 in some files, float64
# in others; both are this float32). ERDDAP shows NaN because it converts; the store cannot.
FILL = np.float32(9.99e10)

ERDDAP = 'https://pae-paha.pacioos.hawaii.edu/erddap'
ERDDAP_IDS = ('roms_hiig', 'roms_hiig_ssh')     # temp/salt/u/v, zeta
METADATA_FILE = HERE / 'erddap_metadata.json'

# Attributes that only drive ERDDAP's own displays and bookkeeping, not the data.
ERDDAP_ONLY = {'_ChunkSizes', '_CoordinateAxisType', '_CoordinateZisPositive', 'actual_range',
               'colorBarMaximum', 'colorBarMinimum', 'colorBarPalette', 'colorBarScale',
               'ioos_category', 'time_origin'}
GLOBAL_ERDDAP_ONLY = {'_CoordSysBuilder', 'cdm_data_type', 'defaultGraphQuery', 'drawLandMask', 'sourceUrl',
                      'infoUrl', 'Easternmost_Easting', 'Westernmost_Easting',
                      'Northernmost_Northing', 'Southernmost_Northing',
                      'time_coverage_start', 'time_coverage_end'}   # coverage: from the store
TITLE = 'Regional Ocean Modeling System (ROMS): Main Hawaiian Islands: Forecast'
BEST_RULE = ('Best time series across the daily forecast runs, as THREDDS FMRC "best": for each '
             'valid time, the most recent run that has it, including its first step. '
             'forecast_reference_time and forecast_period give the run and lead of each step. '
             'A time no run covers would read as missing (none so far).')


def key(day) -> str:
    """Object key under URL_PREFIX of one run's file."""
    d = pd.Timestamp(day)
    return f'{DATASET}/netcdf/{d:%Y}/hiig_forec_{d:%Y%m%d}.nc'


def list_runs() -> pd.DatetimeIndex:
    """The run days whose copies are on Source Cooperative, from an anonymous listing."""
    import re
    from obstore.store import S3Store
    store = S3Store('ocean-icechunks', endpoint='https://data.source.coop', region='us-east-1',
                    skip_signature=True)
    pat = re.compile(r'/hiig_forec_(\d{8})\.nc$')
    days = []
    for batch in store.list(prefix=f'pacioos/{DATASET}/netcdf/'):
        for obj in batch:
            m = pat.search(obj['path'])
            if m:
                days.append(pd.Timestamp(m.group(1)))
    return pd.DatetimeIndex(sorted(days))


# ------------------------------------------------------------------ ERDDAP metadata

def fetch_erddap_rows(dataset_id: str) -> list[list[str]]:
    """The attribute rows of one ERDDAP dataset, as ERDDAP's info service gives them."""
    import fsspec
    raw = fsspec.filesystem('https', client_kwargs={'timeout': None}).cat(
        f'{ERDDAP}/info/{dataset_id}/index.json')
    rows = json.loads(raw)['table']['rows']
    return [r for r in rows if r[0] == 'attribute']


def save_erddap_metadata(path: Path = METADATA_FILE) -> None:
    """Refresh the saved copy from ERDDAP. Review the diff before committing it.

    The coverage attributes (time_coverage_*, time actual_range) change every day; the build
    ignores them, and they are dropped here so a refresh shows only real changes.
    """
    volatile = {('NC_GLOBAL', 'time_coverage_start'), ('NC_GLOBAL', 'time_coverage_end'),
                ('time', 'actual_range')}
    datasets = {i: [r for r in fetch_erddap_rows(i) if (r[1], r[2]) not in volatile]
                for i in ERDDAP_IDS}
    fetched = pd.Timestamp.now('UTC').strftime('%Y-%m-%dT%H:%M:%SZ')
    # One attribute row per line, so a refresh shows up as a readable diff.
    lines = ['{', f' "fetched": {json.dumps(fetched)},',
             f' "source": {json.dumps(f"{ERDDAP}/info/<id>/index.json")},', ' "datasets": {']
    for n, (i, rows) in enumerate(datasets.items()):
        lines.append(f'  {json.dumps(i)}: [')
        lines += [f'   {json.dumps(r, ensure_ascii=False)}' + (',' if k < len(rows) - 1 else '')
                  for k, r in enumerate(rows)]
        lines.append('  ]' + (',' if n < len(datasets) - 1 else ''))
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

    Never raises on a network error: ERDDAP restarts now and then, and the build must not
    depend on it. The daily coverage attributes are not compared.
    """
    snap = json.loads(Path(path).read_text())
    skip = {'time_coverage_start', 'time_coverage_end', 'actual_range'}
    diffs = []
    for i in ERDDAP_IDS:
        try:
            live = _parse(fetch_erddap_rows(i))
        except Exception as exc:                                   # noqa: BLE001
            print(f'ERDDAP did not answer for {i} ({type(exc).__name__}); using the saved copy')
            return None
        saved = _parse(snap['datasets'][i])
        for var in sorted(set(saved) | set(live)):
            for attr in sorted(set(saved.get(var, {})) | set(live.get(var, {})) - skip):
                a, b = saved.get(var, {}).get(attr), live.get(var, {}).get(attr)
                if str(a) != str(b):
                    diffs.append({'dataset': i, 'variable': var, 'attribute': attr,
                                  'saved': a, 'live': b})
    return pd.DataFrame(diffs, columns=['dataset', 'variable', 'attribute', 'saved', 'live'])


def variable_attrs(main: dict, ssh: dict, file_mask_attrs: dict) -> dict:
    """{store variable: attrs}. ERDDAP names latitude/longitude; the store keeps lat/lon.

    ``_FillValue`` is the files' 9.99e10, not ERDDAP's NaN: the store serves the files' bytes.
    """
    attrs = {}
    for name in SCIENCE:
        src = (ssh if name == 'zeta' else main)[name]
        attrs[name] = {k: src[k] for k in ('long_name', 'standard_name', 'units') if k in src}
        attrs[name]['_FillValue'] = FILL
    for store_name, erddap_name in [('lat', 'latitude'), ('lon', 'longitude'), ('depth', 'depth'),
                                    ('time', 'time')]:
        # ERDDAP's time also has missing_value = NaN and calendar; the coordinates have no
        # missing values, and xarray writes units and calendar itself (they are encoding).
        attrs[store_name] = {k: v for k, v in main[erddap_name].items()
                             if k not in ERDDAP_ONLY | {'missing_value', '_FillValue', 'calendar'}
                             and not (store_name == 'time' and k == 'units')}
    attrs['mask'] = dict(file_mask_attrs)      # not in ERDDAP; the file's own
    attrs['forecast_reference_time'] = {
        'standard_name': 'forecast_reference_time',
        'long_name': 'start of the forecast run this step comes from'}
    attrs['forecast_period'] = {
        'standard_name': 'forecast_period', 'units': 'hours',
        'long_name': 'hours since the start of the forecast run this step comes from'}
    return attrs


def metadata_source(fetched: str) -> str:
    """The store's `metadata_source` attribute: where its attributes came from."""
    return (f'Variable and global attributes from PacIOOS ERDDAP datasets {ERDDAP_IDS[0]} and '
            f'{ERDDAP_IDS[1]} ({ERDDAP}/info/{ERDDAP_IDS[0]}/index.html), saved {fetched} in '
            'stores/roms_hiig/erddap_metadata.json of https://github.com/ocean-icechunks/pacioos. '
            'The NetCDF files carry only author, history and title ("Zlevel Model Data"). '
            '_FillValue (9.99e10) and mask are the files\' own. No data values were changed.')


def global_attrs(main: dict, time_index, runs, now=None) -> dict:
    """Global attributes for a store covering `time_index`, built from `runs` (days)."""
    now = pd.Timestamp(now or pd.Timestamp.now('UTC'))
    runs = pd.DatetimeIndex(runs)
    attrs = {k: v for k, v in main['NC_GLOBAL'].items() if k not in GLOBAL_ERDDAP_ONLY}
    attrs.update({
        'title': TITLE,
        'time_coverage_start': f'{time_index[0]:%Y-%m-%dT%H:%M:%SZ}',
        'time_coverage_end': f'{time_index[-1]:%Y-%m-%dT%H:%M:%SZ}',
        'comment': (attrs.get('comment', '') + ' ' + BEST_RULE).strip(),
        'source_files': URL_PREFIX + f'{DATASET}/netcdf/',
        'metadata_source': metadata_source(main.get('_fetched', 'see erddap_metadata.json')),
        'forecast_runs': f'{len(runs)} daily runs, {runs[0]:%Y-%m-%d} to {runs[-1]:%Y-%m-%d}',
        'history': (main['NC_GLOBAL'].get('history', '') + '\n').lstrip()
                   + f'{now:%Y-%m-%dT%H:%M:%SZ} Virtual Icechunk store (best time series) over '
                   'unchanged copies of the forecast NetCDF files; metadata from PacIOOS ERDDAP, '
                   'no data values changed.',
    })
    return attrs


# ------------------------------------------------------------------ the dataset

def build_dataset(scans: list[dict], var_attrs: dict, main: dict) -> xr.Dataset:
    """The best-series virtual dataset over `scans` (pv.scan_nc3 results, one per run).

    The axis is regular 3-hourly from the first run's start to the last run's end; a step no
    run covers gets no reference (it reads as the fill value, NaN once decoded).
    """
    scans = sorted(scans, key=lambda s: s['time'][0])
    best = pv.best_assignment(scans, '3h')
    data = {}
    for name in SCIENCE:
        dims = ('time', 'depth', 'lat', 'lon') if name != 'zeta' else ('time', 'lat', 'lon')
        # For Zarr v3, xarray keeps _FillValue base64-encoded and refuses a plain float on open.
        attrs = dict(var_attrs[name], _FillValue=FillValueCoder.encode(FILL, np.dtype('f4')))
        data[name] = pv.manifest_variable(name, scans, best, dims, attrs, fill_value=FILL)
    c = scans[0]['coords']
    run = best['run'].to_numpy()
    run_start = pd.DatetimeIndex([scans[r]['time'][0] if r >= 0 else pd.NaT
                                  for r in run]).values.astype('datetime64[ns]')
    period = (best.index.values - run_start) / np.timedelta64(1, 'h')     # NaN in a gap
    ds = xr.Dataset(data, coords={
        'time': ('time', best.index.values, var_attrs['time']),
        'depth': ('depth', c['depth'], var_attrs['depth']),
        'lat': ('lat', c['lat'], var_attrs['lat']),
        'lon': ('lon', c['lon'], var_attrs['lon']),
        'forecast_reference_time': ('time', run_start, var_attrs['forecast_reference_time']),
        'forecast_period': ('time', period.astype('f4'), var_attrs['forecast_period']),
    })
    # The mask is int16 in some files and float32 in others, with the same values; the store
    # keeps int16, as the reanalysis store does.
    ds['mask'] = (('lat', 'lon'), c['mask'].astype('int16'), var_attrs['mask'])
    ds.attrs = global_attrs(main, best.index, [s['time'][0] for s in scans])
    # The files' own time units, as float64, each time-length coordinate in one chunk.
    nt = len(best)
    for v in ('time', 'forecast_reference_time'):
        ds[v].encoding = {'units': TIME_UNITS, 'dtype': 'float64', 'chunks': (nt,)}
    ds['forecast_period'].encoding = {'chunks': (nt,)}
    return ds


def repository_config():
    return pv.repository_config(time_chunks_per_manifest=TIME_PER_MANIFEST)


def open_store(storage, ref: str = 'main', chunks=None, **kw) -> xr.Dataset:
    """Open a store as a reader: containers from the saved config, anonymous HTTP to each.

    Pass chunks=None (the default here) for point series: with chunks={} dask runs one task
    per 230 KB chunk and its thread pool, not Zarr's async.concurrency, limits the reads.
    """
    import icechunk
    repo = icechunk.Repository.open(storage)
    auth = {p: icechunk.credentials.HttpAccess for p in repo.config.virtual_chunk_containers or []}
    repo = repo.reopen(authorize_virtual_chunk_access=auth)
    tags = set(repo.list_tags())
    session = repo.readonly_session(tag=ref) if ref in tags else repo.readonly_session(ref)
    return xr.open_zarr(session.store, consolidated=False, chunks=chunks, **kw)
