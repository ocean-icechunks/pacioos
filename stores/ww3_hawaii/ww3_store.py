"""The WaveWatch III Hawaiʻi virtual store, best series: what the notebook and the build share.

Issue #13. Decisions (Eli Holmes, 2026-11-14):

- the THREDDS FMRC "best" rule: for each valid time, the newest run that has it, including its
  first step; ties (two runs starting at the same time) go to the later file name, as THREDDS;
- **a regular hourly axis**: a time no run covers stays on the axis with no reference, so it
  reads as NaN and its ``forecast_reference_time`` is NaT (ERDDAP leaves those times out);
- arrays ``(time, lat, lon)``: the files' length-1 ``z`` dimension is dropped and ``z = 0`` kept
  as a scalar coordinate (the references are the same bytes);
- ``lon`` stays 0–360, as in the files and on ERDDAP;
- a ``best_step_flag`` coordinate on ``time`` (CF flags): 1 = from a cold-start run (its first
  ``Thgt`` field is all zero), 2 = from a file whose first time is not on its name date (the
  2020-04-27 … 05-04 files, probably a day early);
- metadata from PacIOOS's ERDDAP record ``ww3_hawaii``, saved in ``erddap_metadata.json``, with
  a ``metadata_source`` attribute saying so: the files carry almost none;
- one manifest per year of steps (8,760), the convention of the ROMS stores.

The generic reference code (header scans, the best rule, plane manifests, repository config)
is in ``../pacioos_virtual.py``; this module adds what is specific to WW3.
"""
from __future__ import annotations

import json
import re
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
DATASET = 'ww3_hawaii'
SCIENCE = ['Thgt', 'Tper', 'Tdir', 'shgt', 'sper', 'sdir', 'whgt', 'wper', 'wdir']
PLANE = 101 * 141 * 4                      # one (lat, lon) float32 plane, 56,964 bytes
TIME_PER_MANIFEST = 8760                   # one year of hourly steps per manifest
TIME_UNITS = 'minutes since 2008-01-01'    # the files' own
FILL = np.float32(-999.0)                  # the files' _FillValue (ERDDAP shows NaN)
NAME_RE = re.compile(r'/ww3hawaii_(\d{8})\.nc$')

FLAG_COLD_START = 1
FLAG_SUSPECT_TIME = 2
FLAG_ATTRS = {
    'long_name': 'flags on the run each best-series step comes from',
    'flag_masks': np.array([FLAG_COLD_START, FLAG_SUSPECT_TIME], 'i1'),
    'flag_meanings': 'cold_start_run suspect_time_label',
    'comment': ('cold_start_run: the run starts from an all-zero wave field; its spin-up lasts '
                'about 11 h to more than a day (use forecast_period). suspect_time_label: the '
                "file's first time is not on the date in its name (ww3hawaii_20200427.nc .. "
                '20200504.nc start 21Z the day before), so its times are probably a day early. '
                'Both are served as PacIOOS THREDDS/ERDDAP serve them. 0 = neither.'),
}

ERDDAP = 'https://pae-paha.pacioos.hawaii.edu/erddap'
ERDDAP_ID = 'ww3_hawaii'
METADATA_FILE = HERE / 'erddap_metadata.json'
ERDDAP_ONLY = {'_ChunkSizes', '_CoordinateAxisType', '_CoordinateZisPositive', 'actual_range',
               'colorBarMaximum', 'colorBarMinimum', 'colorBarPalette', 'colorBarScale',
               'ioos_category', 'time_origin', 'coordinates', 'missing_value', '_FillValue',
               'calendar'}
GLOBAL_ERDDAP_ONLY = {'_CoordSysBuilder', 'cdm_data_type', 'defaultGraphQuery', 'drawLandMask',
                      'sourceUrl', 'infoUrl', 'Easternmost_Easting', 'Westernmost_Easting',
                      'Northernmost_Northing', 'Southernmost_Northing',
                      'time_coverage_start', 'time_coverage_end'}
BEST_RULE = ('Best time series across the daily forecast runs, as THREDDS FMRC "best": for each '
             'valid time, the most recent run that has it, including its first step; runs that '
             'start at the same time go to the later file name. forecast_reference_time and '
             'forecast_period give the run and lead of each step; best_step_flag marks cold '
             'starts and suspect time labels. Times no run covers stay on the hourly axis and '
             'read as missing.')


# ------------------------------------------------------------------ the files

def list_runs() -> list[str]:
    """Object keys (under URL_PREFIX) of every run on Source Cooperative, from a listing.

    From the listing, not from constructed paths: two files (2020-12-30 and -31) are in the
    2021 year folder.
    """
    from obstore.store import S3Store
    store = S3Store('ocean-icechunks', endpoint='https://data.source.coop', region='us-east-1',
                    skip_signature=True)
    keys = [o['path'] for b in store.list(prefix=f'pacioos/{DATASET}/netcdf/') for o in b
            if NAME_RE.search(o['path'])]
    return sorted((k.removeprefix('pacioos/') for k in keys), key=name_date)


def name_date(key: str) -> pd.Timestamp:
    return pd.Timestamp(NAME_RE.search('/' + key.rsplit('/', 1)[-1]).group(1))


def scan(key: str) -> dict:
    """pv.scan_nc3 plus what the flags need: is the first Thgt field all zero over the sea?"""
    import fsspec
    s = pv.scan_nc3(key)
    v = s['vars']['Thgt']
    raw = fsspec.filesystem('https').cat_file(URL_PREFIX + key, start=int(v['offsets'][0]),
                                              end=int(v['offsets'][0] + v['nbytes'][0]))
    first = np.frombuffer(raw, v['dtype'])
    sea = first != FILL
    s['cold_start'] = bool(sea.any() and (first[sea] == 0).all())
    s['suspect_time'] = s['time'][0].normalize() != name_date(key)
    return s


# ------------------------------------------------------------------ ERDDAP metadata

def fetch_erddap_rows(dataset_id: str = ERDDAP_ID) -> list[list[str]]:
    import fsspec
    raw = fsspec.filesystem('https', client_kwargs={'timeout': None}).cat(
        f'{ERDDAP}/info/{dataset_id}/index.json')
    return [r for r in json.loads(raw)['table']['rows'] if r[0] == 'attribute']


def save_erddap_metadata(path: Path = METADATA_FILE) -> None:
    """Refresh the saved copy from ERDDAP (without the daily-changing coverage). Review the diff."""
    volatile = {('NC_GLOBAL', 'time_coverage_start'), ('NC_GLOBAL', 'time_coverage_end'),
                ('time', 'actual_range')}
    rows = [r for r in fetch_erddap_rows() if (r[1], r[2]) not in volatile]
    fetched = pd.Timestamp.now('UTC').strftime('%Y-%m-%dT%H:%M:%SZ')
    lines = ['{', f' "fetched": {json.dumps(fetched)},',
             f' "source": {json.dumps(f"{ERDDAP}/info/{ERDDAP_ID}/index.json")},',
             f' "datasets": {{', f'  {json.dumps(ERDDAP_ID)}: [']
    lines += [f'   {json.dumps(r, ensure_ascii=False)}' + (',' if k < len(rows) - 1 else '')
              for k, r in enumerate(rows)]
    lines += ['  ]', ' }', '}']
    path.write_text('\n'.join(lines) + '\n')


def _parse(rows) -> dict:
    out = {}
    for _t, var, attr, dtype, value in rows:
        if dtype in ('float', 'double') and ',' not in value:
            value = np.float32(value) if dtype == 'float' else float(value)
        elif dtype in ('float', 'double'):
            value = np.array([float(x) for x in value.split(',')],
                             'f4' if dtype == 'float' else 'f8')
        elif dtype in ('int', 'short', 'byte') and ',' not in value:
            value = int(value)
        out.setdefault(var, {})[attr] = value
    return out


def load_metadata(path: Path = METADATA_FILE) -> tuple[dict, str]:
    """(attrs, fetched): the saved ERDDAP attributes, {variable: {attribute: value}}."""
    snap = json.loads(Path(path).read_text())
    return _parse(snap['datasets'][ERDDAP_ID]), snap['fetched']


def compare_with_live_erddap(path: Path = METADATA_FILE) -> pd.DataFrame | None:
    """Differences between the saved copy and ERDDAP now; None if ERDDAP does not answer."""
    saved, _ = load_metadata(path)
    try:
        live = _parse(fetch_erddap_rows())
    except Exception as exc:                                       # noqa: BLE001
        print(f'ERDDAP did not answer ({type(exc).__name__}); using the saved copy')
        return None
    skip = {'time_coverage_start', 'time_coverage_end', 'actual_range'}
    diffs = []
    for var in sorted(set(saved) | set(live)):
        for attr in sorted((set(saved.get(var, {})) | set(live.get(var, {}))) - skip):
            a, b = saved.get(var, {}).get(attr), live.get(var, {}).get(attr)
            if str(a) != str(b):
                diffs.append({'variable': var, 'attribute': attr, 'saved': a, 'live': b})
    return pd.DataFrame(diffs, columns=['variable', 'attribute', 'saved', 'live'])


def metadata_source(fetched: str) -> str:
    return (f'Variable and global attributes from PacIOOS ERDDAP dataset {ERDDAP_ID} '
            f'({ERDDAP}/info/{ERDDAP_ID}/index.html), saved {fetched} in '
            'stores/ww3_hawaii/erddap_metadata.json of https://github.com/ocean-icechunks/pacioos. '
            'The NetCDF files carry only a title as global metadata ("WaveWatch-III results from '
            'ORE level2 model. Results provided by Ning Li, K.-F. Cheung, PI", padded with dots). '
            '_FillValue (-999) is the files\' own. No data values were changed.')


def variable_attrs(erddap: dict) -> dict:
    """{store variable: attrs}. ERDDAP names latitude/longitude/depth; the store keeps lat/lon/z."""
    attrs = {}
    for name in SCIENCE:
        attrs[name] = {k: v for k, v in erddap[name].items() if k not in ERDDAP_ONLY}
        attrs[name]['_FillValue'] = FILL
    for store_name, erddap_name in (('lat', 'latitude'), ('lon', 'longitude'), ('z', 'depth'),
                                    ('time', 'time')):
        attrs[store_name] = {k: v for k, v in erddap[erddap_name].items()
                             if k not in ERDDAP_ONLY and not (store_name == 'time' and k == 'units')}
    attrs['forecast_reference_time'] = {
        'standard_name': 'forecast_reference_time',
        'long_name': 'start of the forecast run this step comes from'}
    attrs['forecast_period'] = {
        'standard_name': 'forecast_period', 'units': 'hours',
        'long_name': 'hours since the start of the forecast run this step comes from'}
    attrs['best_step_flag'] = dict(FLAG_ATTRS)
    return attrs


def global_attrs(erddap: dict, fetched: str, time_index, run_starts, now=None) -> dict:
    now = pd.Timestamp(now or pd.Timestamp.now('UTC'))
    runs = pd.DatetimeIndex(run_starts)
    attrs = {k: v for k, v in erddap['NC_GLOBAL'].items() if k not in GLOBAL_ERDDAP_ONLY}
    attrs.update({
        'time_coverage_start': f'{time_index[0]:%Y-%m-%dT%H:%M:%SZ}',
        'time_coverage_end': f'{time_index[-1]:%Y-%m-%dT%H:%M:%SZ}',
        'comment': (attrs.get('comment', '') + ' ' + BEST_RULE).strip(),
        'source_files': URL_PREFIX + f'{DATASET}/netcdf/',
        'forecast_runs': f'{len(runs)} runs, {runs[0]:%Y-%m-%dT%HZ} to {runs[-1]:%Y-%m-%dT%HZ}',
        'metadata_source': metadata_source(fetched),
        'history': attrs.get('history', '') + '\n'
                   + f'{now:%Y-%m-%dT%H:%M:%SZ} Virtual Icechunk store (best time series) over '
                   'unchanged copies of the WW3 NetCDF files; metadata from PacIOOS ERDDAP, no data '
                   'values changed.',
    })
    return attrs


# ------------------------------------------------------------------ the dataset

def order_runs(scans: list[dict]) -> list[dict]:
    """Oldest first; runs starting at the same time by file name, so the later name wins."""
    return sorted(scans, key=lambda s: (s['time'][0], s['key'].rsplit('/', 1)[-1]))


def build_dataset(scans: list[dict], var_attrs: dict, erddap: dict, fetched: str) -> xr.Dataset:
    """The best-series virtual dataset over `scans` (scan() results), on a regular hourly axis."""
    scans = order_runs(scans)
    best = pv.best_assignment(scans, '1h')       # stable: among equal starts the later one wins
    data = {}
    for name in SCIENCE:
        attrs = dict(var_attrs[name], _FillValue=FillValueCoder.encode(FILL, np.dtype('f4')))
        data[name] = pv.manifest_variable(name, scans, best, ('time', 'lat', 'lon'), attrs,
                                          fill_value=FILL)
    c = scans[0]['coords']
    run = best['run'].to_numpy()
    run_start = pd.DatetimeIndex([scans[r]['time'][0] if r >= 0 else pd.NaT
                                  for r in run]).values.astype('datetime64[ns]')
    period = (best.index.values - run_start) / np.timedelta64(1, 'h')
    flags = np.zeros(len(best), 'i1')
    for i, r in enumerate(run):
        if r >= 0:
            flags[i] = (FLAG_COLD_START * scans[r]['cold_start']
                        + FLAG_SUSPECT_TIME * scans[r]['suspect_time'])
    ds = xr.Dataset(data, coords={
        'time': ('time', best.index.values, var_attrs['time']),
        'lat': ('lat', c['lat'], var_attrs['lat']),
        'lon': ('lon', c['lon'], var_attrs['lon']),
        'z': ((), np.float32(c['z'][0]), var_attrs['z']),
        'forecast_reference_time': ('time', run_start, var_attrs['forecast_reference_time']),
        'forecast_period': ('time', period.astype('f4'), var_attrs['forecast_period']),
        'best_step_flag': ('time', flags, var_attrs['best_step_flag']),
    })
    ds.attrs = global_attrs(erddap, fetched, best.index, [s['time'][0] for s in scans])
    nt = len(best)
    for v in ('time', 'forecast_reference_time'):
        ds[v].encoding = {'units': TIME_UNITS, 'dtype': 'float64', 'chunks': (nt,)}
    for v in ('forecast_period', 'best_step_flag'):
        ds[v].encoding = {'chunks': (nt,)}
    return ds


def repository_config():
    return pv.repository_config(time_chunks_per_manifest=TIME_PER_MANIFEST)


def open_store(storage, ref: str = 'main', chunks=None, **kw) -> xr.Dataset:
    """Open a store as a reader: containers from the saved config, anonymous HTTP to each."""
    import icechunk
    repo = icechunk.Repository.open(storage)
    auth = {p: icechunk.credentials.HttpAccess for p in repo.config.virtual_chunk_containers or []}
    repo = repo.reopen(authorize_virtual_chunk_access=auth)
    tags = set(repo.list_tags())
    session = repo.readonly_session(tag=ref) if ref in tags else repo.readonly_session(ref)
    return xr.open_zarr(session.store, consolidated=False, chunks=chunks, **kw)
