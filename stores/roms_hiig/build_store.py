"""Production build of the ROMS Hawaiʻi forecast best-series virtual Icechunk store (issue #10).

Four phases, each safe to rerun:

  scan      read the NetCDF-3 header of every run's file on Source Cooperative (read-only,
            anonymous), one JSON line per file in <workdir>/scan.jsonl; resumable
  check     every file has the same structure as the first (shapes, dtypes, record and slab
            sizes, coordinates, mask values, missing_value) and 57 steps from 00Z of its day.
            Byte offsets may differ: the files have four header layouts (see the notebook).
  write     the whole best series in one commit
  validate  from the public URL, anonymously: the time axis (computed, and ERDDAP's if it
            answers), the run behind every step, sampled planes against netCDF-C, point values
            against ERDDAP, land as NaN, timings

The destination is scratch unless --dest production is given:

  scratch     ocean-icechunks/test-repo/pacioos/roms_hiig/icechunk-build
  production  ocean-icechunks/pacioos/roms_hiig/icechunk

Run from this folder, with the venv from requirements.txt and, for write, a Source
Cooperative login (source-coop login --duration 1d --port 8400):

  python build_store.py scan                       # ~5 min with 6 processes
  python build_store.py check
  python build_store.py write --dest scratch       # ~1 min
  python build_store.py validate --dest scratch    # ~5 min
  python build_store.py all --dest scratch         # all four in order

The store is written whole, from the runs on Source Cooperative at the time of the scan. It is
not tagged: it will change every day once the daily update (#4) exists, and each daily commit
is a snapshot. Rerunning write on a store that already holds this exact series does nothing;
on a store holding a different one it stops (updating is #4's job, not this script's).

Decisions (Eli Holmes, 2026-11-14): as the reanalysis (one depth plane per chunk, saved ERDDAP
metadata, one group, lat/lon), title ending ": Forecast", the THREDDS best rule, and a regular
3-hourly axis with any uncovered time kept as a NaN step. See how_store_created.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import forecast_store as fs  # noqa: E402
import pacioos_virtual as pv  # noqa: E402

BUCKET = 'ocean-icechunks'
DESTINATIONS = {
    'scratch': 'test-repo/pacioos/roms_hiig/icechunk-build',
    'production': 'pacioos/roms_hiig/icechunk',
    # a deliberately out-of-date copy, for testing update_store.py end to end
    'update-test': 'test-repo/pacioos/roms_hiig/icechunk-update-test',
}
PUBLIC = 'https://data.source.coop'
MIN_MINUTES = 20              # do not start the write with less time left on the keys


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


# ------------------------------------------------------------------ scan

def _digest(a) -> str:
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()[:16]


def _scan_one(day: str) -> dict:
    """Header of one file, as one JSON-able record. Retries network failures."""
    import warnings
    warnings.simplefilter('ignore')
    import fsspec
    k = fs.key(day)
    err = ''
    for attempt in range(4):
        try:
            size = fsspec.filesystem('https').info(fs.URL_PREFIX + k)['size']
            s = pv.scan_nc3(k)
            c = s['coords']
            return {
                'day': day, 'key': k, 'size': int(size),
                'time': [t.isoformat() for t in s['time']],
                'vars': {n: {'shape': list(s['vars'][n]['shape']), 'dtype': s['vars'][n]['dtype'],
                             'offsets': s['vars'][n]['offsets'].tolist(),
                             'nbytes': s['vars'][n]['nbytes'].tolist(),
                             'missing_value': float(s['vars'][n]['attrs'].get('missing_value', 'nan'))}
                         for n in fs.SCIENCE},
                'mask_dtype': s['vars']['mask']['dtype'],
                # the mask's dtype differs between files; its values must not
                'coords': {'lat': _digest(c['lat']), 'lon': _digest(c['lon']),
                           'depth': _digest(c['depth']), 'mask': _digest(c['mask'].astype('int16'))},
            }
        except Exception as exc:                                   # noqa: BLE001
            err = f'{type(exc).__name__}: {exc}'
            time.sleep(5 * (attempt + 1))
    return {'day': day, 'key': k, 'error': err}


def scan(workdir: Path, procs: int) -> None:
    out = workdir / 'scan.jsonl'
    runs = fs.list_runs()
    recs = load_scan(workdir) if out.exists() else {}
    done = {d for d, r in recs.items() if 'error' not in r}
    todo = [f'{d:%Y-%m-%d}' for d in runs if f'{d:%Y-%m-%d}' not in done]
    log(f'scan: {len(runs)} runs on Source Cooperative ({runs[0]:%Y-%m-%d} .. {runs[-1]:%Y-%m-%d}); '
        f'{len(done)} scanned, {len(todo)} to go, {procs} processes')
    if not todo:
        return
    t0 = time.perf_counter()
    with mp.get_context('spawn').Pool(procs, maxtasksperchild=50) as pool, out.open('a') as f:
        for i, rec in enumerate(pool.imap_unordered(_scan_one, todo, chunksize=4), 1):
            f.write(json.dumps(rec) + '\n')
            f.flush()
            if 'error' in rec:
                log('  error', rec['day'], rec['error'])
            if i % 100 == 0 or i == len(todo):
                rate = i / (time.perf_counter() - t0)
                log(f'  {i}/{len(todo)} ({rate:.1f} files/s, ~{(len(todo) - i) / rate / 60:.0f} min left)')


def load_scan(workdir: Path) -> dict[str, dict]:
    recs = {}
    for line in (workdir / 'scan.jsonl').read_text().splitlines():
        r = json.loads(line)
        if 'error' not in r or r['day'] not in recs:
            recs[r['day']] = r                       # a later success replaces an error
    return recs


# ------------------------------------------------------------------ check

def _structure(r: dict) -> dict:
    """Everything that must agree between files: not the offsets, which shift by layout."""
    # missing_value is float32 in some files and float64 in others: compare it as float32.
    return {n: (v['shape'], v['dtype'], v['nbytes'], np.diff(v['offsets']).tolist(),
                float(np.float32(v['missing_value']))) for n, v in r['vars'].items()} | {'coords': r['coords']}


def check(workdir: Path) -> list[str]:
    """The checked run days, oldest first. Stops the build on any problem."""
    recs = load_scan(workdir)
    runs = [f'{d:%Y-%m-%d}' for d in fs.list_runs()]
    missing = [d for d in runs if d not in recs or 'error' in recs[d]]
    if missing:
        sys.exit(f'check: {len(missing)} files not scanned (first: {missing[:5]}); rerun scan')
    extra = sorted(set(recs) - set(runs))
    if extra:
        log(f'check: {len(extra)} scanned files are no longer listed, ignored: {extra[:5]}')
    ref = _structure(recs[runs[0]])
    problems = []
    for d in runs:
        r = recs[d]
        expected_t = [(pd.Timestamp(d) + pd.Timedelta(hours=3 * i)).isoformat()
                      for i in range(fs.STEPS_PER_RUN)]
        if _structure(r) != ref:
            problems.append((d, 'structure differs from the first file'))
        if r['time'] != expected_t:
            problems.append((d, f'times {r["time"][0]} .. {r["time"][-1]}'))
        if any(np.float32(v['missing_value']) != fs.FILL for v in r['vars'].values()):
            problems.append((d, 'missing_value is not 9.99e10'))
        if any(np.diff(v['offsets']).tolist() != [fs.RECSIZE] * (fs.STEPS_PER_RUN - 1)
               for v in r['vars'].values()):
            problems.append((d, 'record size'))
    if problems:
        for p in problems[:20]:
            log('  ', *p)
        sys.exit(f'check: {len(problems)} problems; the build stops here')
    layouts = pd.Series([(recs[d]['vars']['temp']['offsets'][0], recs[d]['mask_dtype']) for d in runs])
    log(f'check: all {len(runs)} files have the same structure, coordinates and mask values, '
        f'57 steps from 00Z of their day, and missing_value 9.99e10; header layouts '
        + ', '.join(f'temp at {o} with {m} mask: {n}' for (o, m), n in layouts.value_counts().sort_index().items()))
    return runs


# ------------------------------------------------------------------ write

def _scans_for(recs: dict, days: list[str], ref_scan: dict) -> list[dict]:
    """pv-style scans from the checked records; coordinates from the reference header."""
    out = []
    for d in days:
        r = recs[d]
        vars_ = {n: {'shape': tuple(v['shape']), 'dtype': v['dtype'],
                     'offsets': np.array(v['offsets'], 'uint64'), 'nbytes': np.array(v['nbytes'], 'uint64')}
                 for n, v in r['vars'].items()}
        out.append({'key': r['key'], 'format': 'nc3', 'vars': vars_,
                    'time': pd.DatetimeIndex(r['time']), 'coords': ref_scan['coords']})
    return out


def planned_dataset(workdir: Path):
    import warnings
    warnings.simplefilter('ignore')
    runs = check(workdir)
    recs = load_scan(workdir)
    ref_scan = pv.scan_nc3(fs.key(runs[0]))                  # coords, mask, attrs
    main_attrs, ssh_attrs, fetched = fs.load_metadata()
    var_attrs = fs.variable_attrs(main_attrs, ssh_attrs, ref_scan['vars']['mask']['attrs'])
    ds = fs.build_dataset(_scans_for(recs, runs, ref_scan), var_attrs, main_attrs)
    return ds, runs, fetched


def open_destination(dest: str):
    from icechunk_utils import open_source_icechunk_repo
    repo, _storage, _creds, time_left = open_source_icechunk_repo(
        bucket=BUCKET, prefix=DESTINATIONS[dest], config=fs.repository_config(),
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
    ds, runs, fetched = planned_dataset(workdir)
    n_refs = sum(int((ds[n].data.manifest._paths != '').sum()) for n in fs.SCIENCE)
    log(f'write: {len(runs)} runs -> {ds.sizes["time"]} steps '
        f'{ds.attrs["time_coverage_start"]} .. {ds.attrs["time_coverage_end"]}, '
        f'{n_refs:,} references; metadata {fetched}')
    repo, time_left = open_destination(dest)
    log(f'  {BUCKET}/{DESTINATIONS[dest]}; keys valid for {time_left}')
    have = _written(repo)
    if have is not None:
        same = (np.array_equal(have.time.values, ds.time.values)
                and np.array_equal(have.forecast_reference_time.values,
                                   ds.forecast_reference_time.values.astype(have.forecast_reference_time.dtype)))
        if same:
            log('  the store already holds this best series; nothing written')
            return
        sys.exit(f'  the store holds a different series ({have.sizes["time"]} steps, to '
                 f'{have.attrs.get("time_coverage_end")}); updating it is #4, not this script. Stopped.')
    repo.save_config()
    t0 = time.perf_counter()
    session = repo.writable_session('main')
    ds.vz.to_icechunk(session.store)
    snap = session.commit(f'best series: {ds.attrs["forecast_runs"]}, {ds.sizes["time"]} steps')
    log(f'  committed {snap} in {time.perf_counter() - t0:.0f}s')


# ------------------------------------------------------------------ validate

def _erddap_csv(query: str) -> list[str]:
    """Rows of an ERDDAP griddap .csv0 query. urllib, not fsspec: fsspec globs on the [ ]."""
    import urllib.parse
    import urllib.request
    url = f'{fs.ERDDAP}/griddap/' + urllib.parse.quote(query, safe='?=&.,:()_-')
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read().decode().strip().splitlines()


def validate(dest: str) -> None:
    import icechunk
    import netCDF4
    import zarr
    zarr.config.set({'async.concurrency': 128})
    url = f'{PUBLIC}/{BUCKET}/{DESTINATIONS[dest]}'
    storage = icechunk.http_storage(url)

    t0 = time.perf_counter()
    ds = fs.open_store(storage)
    open_s = time.perf_counter() - t0
    raw = fs.open_store(storage, mask_and_scale=False)
    log(f'validate: {url} opened anonymously in {open_s:.2f}s')

    # --- the axis and the run behind every step, computed independently of the build
    runs = pd.DatetimeIndex(sorted(set(fs.list_runs())))
    t = pd.DatetimeIndex(ds.time.values)
    expected = pd.date_range(runs[0], runs[-1] + pd.Timedelta('7D'), freq='3h')
    assert t.equals(expected), f'time axis: {len(t)} steps, {t[0]} .. {t[-1]}'
    frt = pd.DatetimeIndex(ds.forecast_reference_time.values)
    newest = pd.DatetimeIndex([runs[(runs <= x) & (runs >= x - pd.Timedelta('7D'))].max() for x in t])
    assert frt.equals(newest), 'a step comes from the wrong run'
    period = ds.forecast_period.values
    assert np.allclose(period, (t - frt) / pd.Timedelta('1h'), equal_nan=True)
    gaps = int(frt.isna().sum())
    log(f'  time axis: {len(t)} steps {t[0]} .. {t[-1]}, from {len(runs)} runs; every step from the '
        f'newest run that has it; {gaps} uncovered steps')
    assert ds.attrs['title'] == fs.TITLE and ds.salt.attrs['units'] == '1e-3'
    assert ds.attrs['time_coverage_start'] == f'{t[0]:%Y-%m-%dT%H:%M:%SZ}'
    assert ds.attrs['time_coverage_end'] == f'{t[-1]:%Y-%m-%dT%H:%M:%SZ}'

    try:
        e = pd.DatetimeIndex(pd.to_datetime(_erddap_csv('roms_hiig.csv0?time'))).tz_localize(None)
        overlap = e[(e >= t[0]) & (e <= t[-1])]
        log(f'  ERDDAP roms_hiig time: {len(e)} steps {e[0]} .. {e[-1]}; '
            f'{"identical to the store" if e.equals(t) else f"{len(overlap)} within the store span"}')
        assert overlap.isin(t).all(), 'ERDDAP has a time inside the span that the store lacks'
    except AssertionError:
        raise
    except Exception as exc:                                       # noqa: BLE001
        log(f'  ERDDAP did not answer ({type(exc).__name__}); time axis not compared with it')

    # --- sampled planes against netCDF-C: one step per month, plus the first and last steps
    rng = np.random.default_rng(2026)
    picks = {0, len(t) - 1}
    for m in sorted(set(t.to_period('M'))):
        idx = np.where((t.to_period('M') == m) & ~frt.isna())[0]
        picks.add(int(rng.choice(idx)))
    bad, n = [], 0
    for i in sorted(picks):
        lead = int(period[i]) // 3
        with netCDF4.Dataset(fs.URL_PREFIX + fs.key(frt[i]) + '#mode=bytes') as nc:
            for name, k in (('temp', 0), ('salt', 35), ('u', 20), ('v', 5), ('zeta', None)):
                v = nc[name]
                v.set_auto_maskandscale(False)
                exp = v[lead] if k is None else v[lead, k]
                sel = {'time': i} | ({} if k is None else {'depth': k})
                n += 1
                if not np.array_equal(raw[name].isel(sel).values, exp):
                    bad.append((str(t[i]), name, k))
    assert not bad, bad
    log(f'  {n} planes ({len(picks)} steps x 5 variables) identical to netCDF-C')

    # --- point values against ERDDAP (its best series is what PacIOOS serves)
    try:
        lat, lon = float(ds.lat.sel(lat=21.2, method='nearest')), float(ds.lon.sel(lon=-157.9, method='nearest'))
        checked = 0
        for i in sorted(rng.choice(np.where(~frt.isna())[0], 4, replace=False)):
            ts = f'{t[i]:%Y-%m-%dT%H:%M:%SZ}'
            for ds_id, name, depth in (('roms_hiig', 'temp', '[(0.25)]'), ('roms_hiig', 'salt', '[(0.25)]'),
                                       ('roms_hiig_ssh', 'zeta', '')):
                row = _erddap_csv(f'{ds_id}.csv0?{name}[({ts})]{depth}[({lat})][({lon})]')[0].split(',')
                # ERDDAP answers with the grid point it used: it must be the store's own
                assert row[0] == ts and abs(float(row[-3]) - lat) < 1e-4 and abs(float(row[-2]) - lon) < 1e-4, row
                sel = {'time': i} | ({'depth': 0} if depth else {})
                ours = float(ds[name].isel(sel).sel(lat=lat, lon=lon))
                assert abs(ours - float(row[-1])) <= 1e-5 * max(1, abs(ours)), (ts, name, ours, row)
                checked += 1
        log(f'  {checked} point values at {lat:.3f}N {lon:.3f}E equal ERDDAP roms_hiig / roms_hiig_ssh (4 times x temp, salt, zeta)')
    except AssertionError:
        raise
    except Exception as exc:                                       # noqa: BLE001
        log(f'  ERDDAP did not answer ({type(exc).__name__}); point values not compared')

    surface = ds.temp.isel(time=-1, depth=0).values
    assert int(np.isnan(surface).sum()) == int((ds.mask.values == 0).sum()) == 1118
    log('  land reads as NaN (1,118 surface cells, mask == 0)')

    timings = {}
    t0 = time.perf_counter(); ds.temp.isel(time=len(t) // 2, depth=0).load()
    timings['surface map'] = time.perf_counter() - t0
    t0 = time.perf_counter(); ds.temp.isel(time=len(t) // 2).load()
    timings['3-D field, 36 levels'] = time.perf_counter() - t0
    t0 = time.perf_counter()
    series = ds.temp.isel(depth=0).sel(lat=21.2, lon=-157.9, method='nearest').load()
    timings[f'point series, surface, all {len(t):,} steps ({len(t) * fs.PLANE / 1e9:.1f} GB)'] = \
        time.perf_counter() - t0
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
        validate(a.dest)


if __name__ == '__main__':
    main()
