"""Production build of the ROMS Hawaiʻi reanalysis v2.0 virtual Icechunk store (issue #11).

Four phases, each resumable, each safe to rerun:

  scan      read the HDF5 header of every one of the 4,380 files (read-only, anonymous),
            one JSON line per file in <workdir>/scan.jsonl
  check     every file: the expected size, the same chunk offsets, coordinates and mask as
            the first file, and times = its day 00..21Z. Stops the build if any differ.
  write     one commit per year, appended along time, into the destination repository
  validate  from the public URL, anonymously: the full time axis, sampled planes in every
            year against netCDF-C, land as NaN, timings. Tags v2.0 when everything passes.

The destination is scratch unless --dest production is given:

  scratch     ocean-icechunks/test-repo/pacioos/roms_hiig_reanalysis/icechunk-build
  production  ocean-icechunks/pacioos/roms_hiig_reanalysis/icechunk

Run from this folder, with the venv from requirements.txt and, for write, a Source
Cooperative login (source-coop login --duration 1d --port 8400):

  python build_store.py scan                       # ~10-15 min with 6 processes
  python build_store.py check
  python build_store.py write --dest scratch       # ~5 min
  python build_store.py validate --dest scratch    # ~3 min
  python build_store.py all --dest scratch         # all four in order

Decisions (Eli Holmes, 2026-11-14): one depth plane per chunk; metadata from the saved ERDDAP
copy; one group. See how_store_created.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import sys
import time
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import reanalysis_store as rs  # noqa: E402
import pacioos_virtual as pv  # noqa: E402

BUCKET = 'ocean-icechunks'
DESTINATIONS = {
    'scratch': 'test-repo/pacioos/roms_hiig_reanalysis/icechunk-build',
    'production': 'pacioos/roms_hiig_reanalysis/icechunk',
}
PUBLIC = 'https://data.source.coop'
MIN_MINUTES = 20              # do not start a year's commit with less time left on the keys


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


# ------------------------------------------------------------------ scan

def _digest(a) -> str:
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()[:16]


def _scan_one(day: str) -> dict:
    """Header of one file, as one JSON-able record. Retries network failures."""
    import fsspec
    k = rs.key(day)
    for attempt in range(4):
        try:
            size = fsspec.filesystem('https').info(rs.URL_PREFIX + k)['size']
            s = pv.scan_h5(k)
            return {
                'day': day, 'key': k, 'size': int(size),
                'time': [t.isoformat() for t in s['time']],
                'vars': {n: {'shape': list(s['vars'][n]['shape']), 'dtype': s['vars'][n]['dtype'],
                             'offsets': s['vars'][n]['offsets'].tolist(),
                             'nbytes': s['vars'][n]['nbytes'].tolist()} for n in rs.SCIENCE},
                'coords': {c: _digest(s['coords'][c]) for c in ('lat', 'lon', 'depth', 'mask')},
            }
        except Exception as exc:                                   # noqa: BLE001
            err = f'{type(exc).__name__}: {exc}'
            time.sleep(5 * (attempt + 1))
    return {'day': day, 'key': k, 'error': err}


def scan(workdir: Path, procs: int) -> None:
    out = workdir / 'scan.jsonl'
    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            r = json.loads(line)
            if 'error' not in r:
                done.add(r['day'])
    todo = [f'{d:%Y-%m-%d}' for d in rs.ALL_DAYS if f'{d:%Y-%m-%d}' not in done]
    log(f'scan: {len(done)} done, {len(todo)} to go, {procs} processes')
    t0 = time.perf_counter()
    # h5py over HTTPS holds memory per process: few processes, recycled often.
    with mp.get_context('spawn').Pool(procs, maxtasksperchild=50) as pool, out.open('a') as f:
        for i, rec in enumerate(pool.imap_unordered(_scan_one, todo, chunksize=4), 1):
            f.write(json.dumps(rec) + '\n')
            f.flush()
            if 'error' in rec:
                log('  error', rec['day'], rec['error'])
            if i % 200 == 0 or i == len(todo):
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

def check(workdir: Path) -> None:
    recs = load_scan(workdir)
    days = [f'{d:%Y-%m-%d}' for d in rs.ALL_DAYS]
    missing = [d for d in days if d not in recs or 'error' in recs[d]]
    if missing:
        sys.exit(f'check: {len(missing)} files not scanned (first: {missing[:5]}); rerun scan')
    ref = recs[days[0]]
    problems = []
    for d in days:
        r = recs[d]
        expected_t = [(pd.Timestamp(d) + pd.Timedelta(hours=3 * i)).isoformat() for i in range(8)]
        if r['size'] != rs.FILE_SIZE:
            problems.append((d, 'size', r['size']))
        if r['vars'] != ref['vars']:
            problems.append((d, 'chunk layout differs', ''))
        if r['coords'] != ref['coords']:
            problems.append((d, 'coords or mask differ', ''))
        if r['time'] != expected_t:
            problems.append((d, 'times', r['time'][0]))
    if problems:
        for p in problems[:20]:
            log('  ', *p)
        sys.exit(f'check: {len(problems)} problems; the build stops here')
    log(f'check: all {len(days)} files have the same size, chunk offsets, coordinates and mask, '
        'and 8 steps at 00..21Z of their own day')


# ------------------------------------------------------------------ write

def _scans_for(recs: dict, days, ref_scan: dict) -> list[dict]:
    """pv-style scans: the checked offsets of each file, coords from the reference header."""
    out = []
    for d in days:
        r = recs[f'{d:%Y-%m-%d}']
        vars_ = {}
        for n in rs.SCIENCE:
            v = dict(ref_scan['vars'][n])
            v['offsets'] = np.array(r['vars'][n]['offsets'], 'uint64')
            v['nbytes'] = np.array(r['vars'][n]['nbytes'], 'uint64')
            vars_[n] = v
        vars_['mask'] = ref_scan['vars']['mask']
        out.append({'key': r['key'], 'format': 'hdf5', 'vars': vars_,
                    'time': pd.DatetimeIndex(r['time']), 'coords': ref_scan['coords']})
    return out


def open_destination(dest: str):
    from icechunk_utils import open_source_icechunk_repo
    repo, storage, _creds, time_left = open_source_icechunk_repo(
        bucket=BUCKET, prefix=DESTINATIONS[dest], config=rs.repository_config(),
        min_minutes_left=MIN_MINUTES, verbose=False)
    if repo is None:
        sys.exit('Stopped: Source Cooperative keys too close to expiry; log in again and rerun.')
    return repo.reopen(authorize_virtual_chunk_access=pv.reader_authorization()), time_left


def written_steps(repo) -> pd.DatetimeIndex:
    import xarray as xr
    try:
        ds = xr.open_zarr(repo.readonly_session('main').store, consolidated=False, chunks=None)
        return pd.DatetimeIndex(ds.time.values)
    except Exception:                                              # noqa: BLE001
        return pd.DatetimeIndex([])


def write(workdir: Path, dest: str, years: list[int] | None) -> None:
    check(workdir)
    recs = load_scan(workdir)
    ref_scan = pv.scan_h5(rs.key(rs.ALL_DAYS[0]))           # coords, mask, attrs, shapes
    main_attrs, ssh_attrs, fetched = rs.load_metadata()
    var_attrs = rs.variable_attrs(main_attrs, ssh_attrs, ref_scan['vars']['mask']['attrs'])

    repo, time_left = open_destination(dest)
    log(f'write: {BUCKET}/{DESTINATIONS[dest]}; keys valid for {time_left}; metadata {fetched}')
    have = written_steps(repo)
    if len(have) == 0:
        repo.save_config()
    years = years or sorted(set(rs.ALL_DAYS.year))
    for y in years:
        days = rs.ALL_DAYS[rs.ALL_DAYS.year == y]
        steps = rs.STEPS[rs.STEPS.year == y]
        if len(have) and steps.isin(have).all():
            log(f'  {y}: already written, skipped')
            continue
        if len(have) and steps[0] != have[-1] + pd.Timedelta(hours=3):
            sys.exit(f'  {y}: the store ends at {have[-1]}; years must be written in order')
        repo, time_left = open_destination(dest)                  # fresh keys per year
        t0 = time.perf_counter()
        ds = rs.build_dataset(_scans_for(recs, days, ref_scan), var_attrs, main_attrs)
        span = pd.DatetimeIndex(np.concatenate([have.values, ds.time.values]))
        ds.attrs = rs.global_attrs(main_attrs, span)          # an append rewrites root attrs
        session = repo.writable_session('main')
        if len(have) == 0:
            ds.vz.to_icechunk(session.store)
        else:
            ds.drop_vars(['depth', 'lat', 'lon', 'mask']).vz.to_icechunk(
                session.store, append_dim='time')
        session.commit(f'{y}: {len(days)} files, {len(steps)} steps')
        have = span
        log(f'  {y}: {len(days)} files, {len(steps)} steps, committed in '
            f'{time.perf_counter() - t0:.0f}s (keys: {time_left} left)')
    log(f'write: store holds {len(have)} steps, {have[0]} .. {have[-1]}')


# ------------------------------------------------------------------ validate

def validate(dest: str, tag: bool = True) -> None:
    import icechunk
    import netCDF4
    import zarr
    zarr.config.set({'async.concurrency': 128})
    url = f'{PUBLIC}/{BUCKET}/{DESTINATIONS[dest]}'
    storage = icechunk.http_storage(url)

    t0 = time.perf_counter()
    ds = rs.open_store(storage)
    open_s = time.perf_counter() - t0
    raw = rs.open_store(storage, mask_and_scale=False)
    log(f'validate: {url} opened anonymously in {open_s:.2f}s')

    t = pd.DatetimeIndex(ds.time.values)
    assert t.equals(rs.STEPS), f'time axis: {len(t)} steps, {t[0]} .. {t[-1]}'
    assert dict(ds.sizes) == {'time': 35040, 'depth': 36, 'lat': 195, 'lon': 295}
    assert ds.attrs['time_coverage_start'] == '2009-01-01T00:00:00Z'
    assert ds.attrs['time_coverage_end'] == '2020-12-28T21:00:00Z'
    assert ds.attrs['title'] == rs.TITLE and ds.temp.attrs['units'] == 'Celsius'
    log('  time axis = the 35,040 steps 2009-01-01 .. 2020-12-28T21Z; sizes, attributes ok')

    rng = np.random.default_rng(2026)
    bad, n = [], 0
    for y in sorted(set(t.year)):
        idx = np.where(t.year == y)[0]
        for i in sorted(rng.choice(idx, 2, replace=False)):
            day, lead = t[i].normalize(), t[i].hour // 3
            with netCDF4.Dataset(rs.URL_PREFIX + rs.key(day) + '#mode=bytes') as nc:
                for name, k in (('temp', 0), ('salt', 35), ('u', 20), ('v', 5), ('zeta', None)):
                    v = nc[name]
                    v.set_auto_maskandscale(False)
                    exp = v[lead] if k is None else v[lead, k]
                    sel = {'time': int(i)} | ({} if k is None else {'depth': k})
                    n += 1
                    if not np.array_equal(raw[name].isel(sel).values, exp):
                        bad.append((str(t[i]), name, k))
    assert not bad, bad
    log(f'  {n} planes (2 steps per year x 5 variables) identical to netCDF-C')

    surface = ds.temp.isel(time=-1, depth=0).values
    assert int(np.isnan(surface).sum()) == int((ds.mask.values == 0).sum()) == 1118
    log('  land reads as NaN (1,118 surface cells, mask == 0)')

    timings = {}
    t0 = time.perf_counter(); ds.temp.isel(time=20000, depth=0).load()
    timings['surface map'] = time.perf_counter() - t0
    t0 = time.perf_counter(); ds.temp.isel(time=20000).load()
    timings['3-D field, 36 levels'] = time.perf_counter() - t0
    t0 = time.perf_counter()
    series = ds.temp.isel(depth=0).sel(lat=21.2, lon=-157.9, method='nearest').load()
    timings['point series, surface, 12 years (35,040 reads, 8.1 GB)'] = time.perf_counter() - t0
    assert not np.isnan(series).any()
    for k, s in timings.items():
        log(f'  {k:55s} {s:7.1f}s')

    if tag:
        repo, _ = open_destination(dest)
        tags = set(repo.list_tags())
        if 'v2.0' in tags:
            log('  tag v2.0 already exists; not moved')
        else:
            snap = next(iter(repo.ancestry(branch='main'))).id
            repo.create_tag('v2.0', snapshot_id=snap)
            log(f'  tagged v2.0 -> {snap}')
    log('validate: passed')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('phase', choices=['scan', 'check', 'write', 'validate', 'all'])
    ap.add_argument('--dest', choices=sorted(DESTINATIONS), default='scratch')
    ap.add_argument('--workdir', type=Path, default=HERE / 'out')
    ap.add_argument('--procs', type=int, default=6)
    ap.add_argument('--years', type=int, nargs='*', help='write only these years (in order)')
    ap.add_argument('--no-tag', action='store_true', help='validate without tagging v2.0')
    a = ap.parse_args()
    a.workdir.mkdir(parents=True, exist_ok=True)
    if a.dest == 'production':
        log('DESTINATION IS PRODUCTION:', f'{BUCKET}/{DESTINATIONS["production"]}')
    if a.phase in ('scan', 'all'):
        scan(a.workdir, a.procs)
    if a.phase in ('check', 'all'):
        check(a.workdir)
    if a.phase in ('write', 'all'):
        write(a.workdir, a.dest, a.years)
    if a.phase in ('validate', 'all'):
        validate(a.dest, tag=not a.no_tag)


if __name__ == '__main__':
    main()
