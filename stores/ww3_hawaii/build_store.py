"""Production build of the WaveWatch III Hawaiʻi best-series virtual Icechunk store (issue #13).

  scan      read the NetCDF-3 header (and the first Thgt plane) of every run on Source
            Cooperative, one JSON line per file in <workdir>/scan.jsonl; resumable, read-only
  check     every file has the same structure (dtypes, plane and record sizes, lat/lon/z values,
            time units) and consecutive hourly times; reports the run lengths and the flags
  write     the whole best series in one commit
  validate  from the public URL, anonymously: the regular axis, the run behind every step
            (computed independently, ties to the later name), the covered steps against ERDDAP's
            times, the flags, sampled planes against netCDF-C, point values against ERDDAP,
            timings

The destination is scratch unless --dest production is given:

  scratch     ocean-icechunks/test-repo/pacioos/ww3_hawaii/icechunk-build
  production  ocean-icechunks/pacioos/ww3_hawaii/icechunk

  python build_store.py scan        # ~15 min with 6 processes
  python build_store.py check
  python build_store.py write --dest scratch
  python build_store.py validate --dest scratch

Decisions (Eli Holmes, 2026-11-14): see ww3_store.py and issue #13.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import pacioos_virtual as pv  # noqa: E402
import ww3_store as ws  # noqa: E402

BUCKET = 'ocean-icechunks'
DESTINATIONS = {
    'scratch': 'test-repo/pacioos/ww3_hawaii/icechunk-build',
    'production': 'pacioos/ww3_hawaii/icechunk',
}
PUBLIC = 'https://data.source.coop'
MIN_MINUTES = 20
RECSIZE = 512_680                       # one record: time + 9 planes


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def _digest(a) -> str:
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()[:16]


# ------------------------------------------------------------------ scan

def _scan_one(key: str) -> dict:
    import warnings
    warnings.simplefilter('ignore')
    err = ''
    for attempt in range(4):
        try:
            s = ws.scan(key)
            v = s['vars']
            return {
                'key': key, 'time': [t.isoformat() for t in s['time']],
                'time_units': v['time']['attrs']['units'],
                'cold_start': s['cold_start'], 'suspect_time': bool(s['suspect_time']),
                'vars': {n: {'shape': list(v[n]['shape']), 'dtype': v[n]['dtype'],
                             'offsets': v[n]['offsets'].tolist(), 'nbytes': v[n]['nbytes'].tolist(),
                             'fill': float(v[n]['attrs'].get('_FillValue', 'nan'))} for n in ws.SCIENCE},
                'coords': {c: _digest(s['coords'][c]) for c in ('lat', 'lon', 'z')},
            }
        except Exception as exc:                                   # noqa: BLE001
            err = f'{type(exc).__name__}: {exc}'
            time.sleep(5 * (attempt + 1))
    return {'key': key, 'error': err}


def load_scan(workdir: Path) -> dict[str, dict]:
    recs = {}
    p = workdir / 'scan.jsonl'
    if p.exists():
        for line in p.read_text().splitlines():
            r = json.loads(line)
            if 'error' not in r or r['key'] not in recs:
                recs[r['key']] = r
    return recs


def scan(workdir: Path, procs: int) -> None:
    keys = ws.list_runs()
    recs = load_scan(workdir)
    todo = [k for k in keys if k not in recs or 'error' in recs[k]]
    log(f'scan: {len(keys)} runs on Source Cooperative; {len(keys) - len(todo)} scanned, '
        f'{len(todo)} to go, {procs} processes')
    if not todo:
        return
    t0 = time.perf_counter()
    with mp.get_context('spawn').Pool(procs, maxtasksperchild=200) as pool, \
            (workdir / 'scan.jsonl').open('a') as f:
        for i, rec in enumerate(pool.imap_unordered(_scan_one, todo, chunksize=8), 1):
            f.write(json.dumps(rec) + '\n')
            f.flush()
            if 'error' in rec:
                log('  error', rec['key'], rec['error'])
            if i % 500 == 0 or i == len(todo):
                rate = i / (time.perf_counter() - t0)
                log(f'  {i}/{len(todo)} ({rate:.1f} files/s, ~{(len(todo) - i) / rate / 60:.0f} min left)')


# ------------------------------------------------------------------ check

def _structure(r: dict) -> dict:
    """What must agree between files: not the offsets (two header layouts) nor the run length."""
    return {'units': r['time_units'], 'coords': r['coords'],
            'vars': {n: (v['shape'][1:], v['dtype'], sorted(set(v['nbytes'])),
                         sorted(set(np.diff(v['offsets']).tolist())), v['fill'])
                     for n, v in r['vars'].items()}}


def check(workdir: Path) -> list[str]:
    recs = load_scan(workdir)
    keys = ws.list_runs()
    missing = [k for k in keys if k not in recs or 'error' in recs[k]]
    if missing:
        sys.exit(f'check: {len(missing)} files not scanned (first: {missing[:3]}); rerun scan')
    ref = _structure(recs[keys[0]])
    problems = []
    for k in keys:
        r = recs[k]
        if _structure(r) != ref:
            problems.append((k, 'structure differs from the first file'))
        t = pd.DatetimeIndex(r['time'])
        if not (np.diff(t) == np.timedelta64(1, 'h')).all() or (t != t.floor('h')).any():
            problems.append((k, 'times not consecutive hours'))
        if any(n != [ws.PLANE] for n in [sorted(set(v['nbytes'])) for v in r['vars'].values()]):
            problems.append((k, 'plane size'))
        if any(len(v['offsets']) > 1 and set(np.diff(v['offsets'])) != {RECSIZE} for v in r['vars'].values()):
            problems.append((k, 'record size'))
    if problems:
        for p in problems[:20]:
            log('  ', *p)
        sys.exit(f'check: {len(problems)} problems; the build stops here')
    lengths = pd.Series([len(recs[k]['time']) for k in keys]).value_counts().to_dict()
    layouts = pd.Series([recs[k]['vars']['Thgt']['offsets'][0] for k in keys]).value_counts().to_dict()
    cold = [k for k in keys if recs[k]['cold_start']]
    suspect = [k.rsplit('/', 1)[-1] for k in keys if recs[k]['suspect_time']]
    log(f'check: all {len(keys)} files have the same structure and consecutive hourly times; '
        f'run lengths {lengths}; first Thgt offsets {layouts}; {len(cold)} cold starts; '
        f'{len(suspect)} files whose first time is not on their name date: {suspect}')
    return keys


# ------------------------------------------------------------------ write

def scans_from(recs: dict, keys: list[str], ref_scan: dict) -> list[dict]:
    out = []
    for k in keys:
        r = recs[k]
        vars_ = {n: {'shape': tuple(v['shape']), 'dtype': v['dtype'],
                     'offsets': np.array(v['offsets'], 'uint64'), 'nbytes': np.array(v['nbytes'], 'uint64')}
                 for n, v in r['vars'].items()}
        out.append({'key': k, 'format': 'nc3', 'vars': vars_, 'time': pd.DatetimeIndex(r['time']),
                    'coords': ref_scan['coords'], 'cold_start': r['cold_start'],
                    'suspect_time': r['suspect_time']})
    return out


def planned_dataset(workdir: Path):
    import warnings
    warnings.simplefilter('ignore')
    keys = check(workdir)
    recs = load_scan(workdir)
    ref_scan = pv.scan_nc3(keys[-1])
    erddap, fetched = ws.load_metadata()
    var_attrs = ws.variable_attrs(erddap)
    ds = ws.build_dataset(scans_from(recs, keys, ref_scan), var_attrs, erddap, fetched)
    return ds, keys, fetched


def open_destination(dest: str):
    from icechunk_utils import open_source_icechunk_repo
    repo, _s, _c, time_left = open_source_icechunk_repo(
        bucket=BUCKET, prefix=DESTINATIONS[dest], config=ws.repository_config(),
        min_minutes_left=MIN_MINUTES, verbose=False)
    if repo is None:
        sys.exit('Stopped: Source Cooperative keys too close to expiry; log in again and rerun.')
    return repo.reopen(authorize_virtual_chunk_access=pv.reader_authorization()), time_left


def _written(repo):
    import xarray as xr
    try:
        return xr.open_zarr(repo.readonly_session('main').store, consolidated=False, chunks=None)
    except Exception:                                              # noqa: BLE001
        return None


def write(workdir: Path, dest: str) -> None:
    ds, keys, fetched = planned_dataset(workdir)
    n_refs = sum(int((ds[n].data.manifest._paths != '').sum()) for n in ws.SCIENCE)
    gaps = int(np.isnat(ds.forecast_reference_time.values).sum())
    log(f'write: {len(keys)} runs -> {ds.sizes["time"]} hourly steps '
        f'{ds.attrs["time_coverage_start"]} .. {ds.attrs["time_coverage_end"]} ({gaps} uncovered), '
        f'{n_refs:,} references; metadata {fetched}')
    repo, time_left = open_destination(dest)
    log(f'  {BUCKET}/{DESTINATIONS[dest]}; keys valid for {time_left}')
    have = _written(repo)
    if have is not None:
        same = (np.array_equal(have.time.values, ds.time.values) and np.array_equal(
            have.forecast_reference_time.values.astype('M8[ns]'),
            ds.forecast_reference_time.values.astype('M8[ns]'), equal_nan=True))
        if same:
            log('  the store already holds this best series; nothing written')
            return
        sys.exit('  the store holds a different series; updating it is the daily update\'s job. Stopped.')
    repo.save_config()
    t0 = time.perf_counter()
    session = repo.writable_session('main')
    ds.vz.to_icechunk(session.store)
    snap = session.commit(f'best series: {ds.attrs["forecast_runs"]}, {ds.sizes["time"]} steps')
    log(f'  committed {snap} in {time.perf_counter() - t0:.0f}s')


# ------------------------------------------------------------------ validate

def _erddap_csv(query: str) -> list[str]:
    url = f'{ws.ERDDAP}/griddap/' + urllib.parse.quote(query, safe='?=&.,:()_-')
    with urllib.request.urlopen(url, timeout=300) as r:
        return r.read().decode().strip().splitlines()


def validate(dest: str, workdir: Path) -> None:
    import icechunk
    import netCDF4
    import zarr
    zarr.config.set({'async.concurrency': 128})
    url = f'{PUBLIC}/{BUCKET}/{DESTINATIONS[dest]}'
    storage = icechunk.http_storage(url)
    t0 = time.perf_counter()
    ds = ws.open_store(storage)
    open_s = time.perf_counter() - t0
    raw = ws.open_store(storage, mask_and_scale=False)
    log(f'validate: {url} opened anonymously in {open_s:.2f}s')

    # --- the run behind every step, computed independently: newest start, ties to the later name
    recs = load_scan(workdir)
    keys = ws.list_runs()
    runs = pd.DataFrame({'key': keys, 'name': [k.rsplit('/', 1)[-1] for k in keys],
                         'start': [pd.Timestamp(recs[k]['time'][0]) for k in keys],
                         'end': [pd.Timestamp(recs[k]['time'][-1]) for k in keys],
                         'cold': [recs[k]['cold_start'] for k in keys],
                         'suspect': [recs[k]['suspect_time'] for k in keys]}).sort_values(['start', 'name'])
    t = pd.DatetimeIndex(ds.time.values)
    expected_axis = pd.date_range(runs['start'].min(), runs['end'].max(), freq='h')
    assert t.equals(expected_axis), f'axis {len(t)} steps {t[0]} .. {t[-1]}'
    winner = pd.Series(pd.NaT, index=t, dtype='datetime64[ns]')
    wname = pd.Series('', index=t, dtype=object)
    for r in runs.itertuples():                      # oldest first; later ones overwrite
        sl = (t >= r.start) & (t <= r.end)
        winner[sl] = r.start
        wname[sl] = r.name
    frt = pd.DatetimeIndex(ds.forecast_reference_time.values)
    assert frt.equals(pd.DatetimeIndex(winner.values)), 'a step comes from the wrong run'
    gaps = int(frt.isna().sum())
    log(f'  axis: {len(t)} hourly steps {t[0]} .. {t[-1]}, {gaps} uncovered; every step from the '
        'newest run (ties to the later name)')

    # --- flags agree with the runs
    flag = ds.best_step_flag.values
    cold_names = set(runs.loc[runs['cold'], 'name'])
    susp_names = set(runs.loc[runs['suspect'], 'name'])
    exp_flag = np.array([(ws.FLAG_COLD_START * (n in cold_names) + ws.FLAG_SUSPECT_TIME * (n in susp_names))
                         if n else 0 for n in wname], 'i1')
    assert np.array_equal(flag, exp_flag), 'flags'
    log(f'  flags: {int(((flag & 1) > 0).sum())} steps from {len(cold_names)} cold-start runs; '
        f'{int(((flag & 2) > 0).sum())} steps from {len(susp_names)} suspect files')

    # --- the covered steps against ERDDAP's times
    try:
        e = pd.DatetimeIndex(pd.to_datetime(_erddap_csv('ww3_hawaii.csv0?time'))).tz_localize(None)
        covered = t[~frt.isna()]
        span = e[(e >= covered[0]) & (e <= covered[-1])]
        log(f'  ERDDAP ww3_hawaii: {len(e)} times {e[0]} .. {e[-1]}; within the store span '
            f'{len(span)}, the store covers {len(covered)}: '
            f'{"identical" if span.equals(covered) else "DIFFERENT"}')
        assert span.equals(covered), 'covered steps differ from ERDDAP'
    except AssertionError:
        raise
    except Exception as exc:                                       # noqa: BLE001
        log(f'  ERDDAP did not answer ({type(exc).__name__}); axis not compared with it')

    # --- sampled planes against netCDF-C: one covered step per year, plus first and last
    rng = np.random.default_rng(2026)
    picks = {int(np.where(~frt.isna())[0][0]), int(np.where(~frt.isna())[0][-1])}
    for y in sorted(set(t.year)):
        idx = np.where((t.year == y) & ~frt.isna())[0]
        picks.add(int(rng.choice(idx)))
    n = 0
    for i in sorted(picks):
        key = runs.loc[runs['name'] == wname.iloc[i], 'key'].iloc[0]
        lead = int(ds.forecast_period.values[i])
        with netCDF4.Dataset(ws.URL_PREFIX + key + '#mode=bytes') as nc:
            for name in ('Thgt', 'Tdir', 'sper', 'wdir'):
                v = nc[name]
                v.set_auto_maskandscale(False)
                assert np.array_equal(raw[name].isel(time=i).values, v[lead, 0]), (str(t[i]), name)
                n += 1
    log(f'  {n} planes ({len(picks)} steps x 4 variables) identical to netCDF-C')

    # --- point values against ERDDAP, at times no newer (uncopied) run has re-pointed
    try:
        lat, lon = float(ds.lat.sel(lat=20.5, method='nearest')), float(ds.lon.sel(lon=202.5, method='nearest'))
        safe = np.where(~frt.isna() & (t < runs['start'].max()))[0]
        checked = nan_pairs = 0
        for i in sorted(rng.choice(safe, 4, replace=False)):
            ts = f'{t[i]:%Y-%m-%dT%H:%M:%SZ}'
            for name in ('Thgt', 'Tper', 'wdir'):
                row = _erddap_csv(f'ww3_hawaii.csv0?{name}[({ts})][(0.0)][({lat})][({lon})]')[0].split(',')
                assert row[0] == ts and abs(float(row[-3]) - lat) < 1e-4 and abs(float(row[-2]) - lon) < 1e-4, row
                ours, theirs = float(ds[name].isel(time=i).sel(lat=lat, lon=lon)), float(row[-1])
                both_nan = np.isnan(ours) and np.isnan(theirs)      # e.g. wdir with no wind sea
                assert both_nan or abs(ours - theirs) <= 1e-4 * max(1, abs(ours)), (ts, name, ours, row)
                checked += 1
                nan_pairs += both_nan
        log(f'  {checked} point values at {lat:.2f}N {lon:.2f}E equal ERDDAP ww3_hawaii (4 times x Thgt, '
            f'Tper, wdir; {nan_pairs} of them NaN on both sides)')
    except AssertionError:
        raise
    except Exception as exc:                                       # noqa: BLE001
        log(f'  ERDDAP did not answer ({type(exc).__name__}); point values not compared')

    assert ds.attrs['title'] == 'WaveWatch III (WW3) Hawaii Regional Wave Model'
    assert 'ERDDAP' in ds.attrs['metadata_source'] and float(ds.z) == 0.0
    timings = {}
    t0 = time.perf_counter(); ds.Thgt.isel(time=len(t) // 2).load()
    timings['one map'] = time.perf_counter() - t0
    t0 = time.perf_counter()
    series = ds.Thgt.sel(lat=20.5, lon=202.5, method='nearest').load()
    timings[f'point series, all {len(t):,} steps ({len(t) * ws.PLANE / 1e9:.1f} GB)'] = time.perf_counter() - t0
    assert int(np.isnan(series).sum()) == gaps
    for k, s in timings.items():
        log(f'  {k:55s} {s:7.1f}s')
    log('validate: passed')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('phase', choices=['scan', 'check', 'write', 'validate', 'all'])
    ap.add_argument('--dest', choices=sorted(DESTINATIONS), default='scratch')
    ap.add_argument('--workdir', type=Path, default=HERE / 'out')
    ap.add_argument('--procs', type=int, default=6)
    a = ap.parse_args()
    a.workdir.mkdir(parents=True, exist_ok=True)
    if a.dest == 'production':
        log('DESTINATION IS PRODUCTION:', f'{BUCKET}/{DESTINATIONS["production"]}')
    if a.phase in ('scan', 'all'):
        scan(a.workdir, a.procs)
    if a.phase in ('check', 'all'):
        check(a.workdir)
    if a.phase in ('write', 'all'):
        write(a.workdir, a.dest)
    if a.phase in ('validate', 'all'):
        validate(a.dest, a.workdir)


if __name__ == '__main__':
    main()
