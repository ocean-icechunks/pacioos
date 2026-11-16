"""Tests of update_store.py against local Icechunk repos (no credentials; reads the public copies).

Each scenario builds a store from a subset of the runs, applies update_store.update with the
plan for more runs, and checks the result against a fresh full build of that plan, read back
from storage. Needs the header scan in out/scan.jsonl (python build_store.py scan).

The runs are 2026-09-15 .. 2026-11-11, pinned so new runs do not change the expected counts.
WW3 runs start at 06Z on their name date and have 181 hourly steps; this window has days with
no run and five cold-start runs, so the flags are exercised too.

  python test_update_store.py        # a few minutes
"""
import shutil
import sys
import tempfile
import warnings
from pathlib import Path

warnings.simplefilter('ignore')
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]

import icechunk  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import xarray as xr  # noqa: E402

import best_series_update as bsu  # noqa: E402
import build_store as bs  # noqa: E402
import pacioos_virtual as pv  # noqa: E402
import update_store as us  # noqa: E402
import ww3_store as ws  # noqa: E402

icechunk.set_logs_filter('error')
RECS = bs.load_scan(HERE / 'out')
RUNS = [k for k in sorted(RECS, key=ws.name_date)
        if 'error' not in RECS[k] and '2026-09-15' <= f'{ws.name_date(k):%Y-%m-%d}' <= '2026-11-11']
REF = bsu.retry(lambda: pv.scan_nc3(RUNS[-1]), 'scan the reference file')
ERDDAP, FETCHED = ws.load_metadata()
VA = ws.variable_attrs(ERDDAP)
WORK = Path(tempfile.mkdtemp(prefix='pacioos-ww3-update-test-'))


def day(d):
    return next(k for k in RUNS if f'{ws.name_date(k):%Y-%m-%d}' == d)


def plan(keys):
    return ws.build_dataset(bs.scans_from(RECS, list(keys), REF), VA, ERDDAP, FETCHED)


def new_store(name, keys):
    storage = icechunk.local_filesystem_storage(str(WORK / name))
    repo = icechunk.Repository.create(storage, config=ws.repository_config(),
                                      authorize_virtual_chunk_access=pv.reader_authorization())
    repo.save_config()
    s = repo.writable_session('main')
    plan(keys).vz.to_icechunk(s.store)
    s.commit(f'initial: {len(keys)} runs')
    return repo, storage


def same_as_fresh(storage, keys, name):
    """The updated store reads exactly like a fresh build of the same runs (refs compared via data)."""
    _, fresh_storage = new_store(name + '-fresh', keys)
    bsu.retry(lambda: _compare(storage, fresh_storage), f'compare {name} with a fresh build')


def _compare(storage, fresh_storage):
    a = ws.open_store(storage, mask_and_scale=False)
    b = ws.open_store(fresh_storage, mask_and_scale=False)
    for c in ('time', 'forecast_reference_time', 'forecast_period', 'best_step_flag'):
        assert np.array_equal(a[c].values, b[c].values,
                              equal_nan=a[c].dtype.kind in 'fM'), c
    assert dict(a.sizes) == dict(b.sizes)
    assert a.attrs['time_coverage_end'] == b.attrs['time_coverage_end']
    assert a.attrs['forecast_runs'] == b.attrs['forecast_runs']
    # Thgt at a sea point (the one validate compares with ERDDAP) over the last 400 steps
    pt = dict(lat=20.5, lon=202.5, method='nearest')
    x = a.Thgt.isel(time=slice(-400, None)).sel(**pt).values
    assert np.isfinite(x).any(), 'the point is not at sea'
    assert np.array_equal(x, b.Thgt.isel(time=slice(-400, None)).sel(**pt).values, equal_nan=True)


def cold_steps(storage):
    return bsu.retry(lambda: _cold_steps(storage), 'count cold-start steps')


def _cold_steps(storage):
    return int((ws.open_store(storage).best_step_flag.values & ws.FLAG_COLD_START > 0).sum())


def scenario(title):
    print(f'\n=== {title}', flush=True)


results = []
print(f'{len(RUNS)} runs, {RUNS[0]} .. {RUNS[-1]}')

scenario('A. three missed days are caught up; a rerun commits nothing')
keys = RUNS[:-3]
repo, st = new_store('A', keys)
before = next(iter(repo.ancestry(branch='main'))).id
ch = us.update(repo, st, plan(RUNS))
print(f'   appended {ch["appended"]}, re-pointed {ch["repointed"]}')
# the old store ended 181 h after its last run (11-08 06Z -> 11-15 18Z); each new run starts 24 h
# later, so 72 steps are new and the newest runs take over 11-09 06Z .. 11-15 18Z (157 steps)
assert f'{ws.name_date(keys[-1]):%Y-%m-%d}' == '2026-11-08'
assert ch['appended'] == 72 and ch['repointed'] == 6 * 24 + 13, ch
same_as_fresh(st, RUNS, 'A')
assert us.update(repo, st, plan(RUNS)) is None
r = icechunk.Repository.open(st, authorize_virtual_chunk_access=pv.reader_authorization())
prev = xr.open_zarr(r.readonly_session(snapshot_id=before).store, consolidated=False, chunks=None)
assert prev.sizes['time'] == plan(keys).sizes['time'], 'the previous snapshot changed'
print('   matches a fresh build; rerun: nothing committed; the previous snapshot still has '
      f'{prev.sizes["time"]} steps')
results.append('A passed')

scenario('B. a run that arrives late re-points only the steps it now wins')
late = day('2026-11-05')
repo, st = new_store('B', [k for k in RUNS if k != late])
ch = us.update(repo, st, plan(RUNS))
assert ch['appended'] == 0 and ch['repointed'] == 24, ch      # 11-05 06Z .. 11-06 05Z
assert [f'{r:%Y-%m-%d}' for r in ch['runs']] == ['2026-11-05']
same_as_fresh(st, RUNS, 'B')
print('   24 steps re-pointed to the late run, nothing appended; matches a fresh build')
results.append('B passed')

scenario('C. a late cold-start run re-points its steps and flags them')
late = day('2026-10-27')
assert RECS[late]['cold_start']
repo, st = new_store('C', [k for k in RUNS if k != late])
n_before = cold_steps(st)
ch = us.update(repo, st, plan(RUNS))
# no 10-28 run, so the 10-27 run wins 10-27 06Z .. 10-29 05Z
assert ch['appended'] == 0 and ch['repointed'] == 48, ch
same_as_fresh(st, RUNS, 'C')
assert cold_steps(st) == n_before + 48, (n_before, cold_steps(st))
print(f'   48 steps re-pointed and flagged cold start ({n_before} -> {cold_steps(st)}); matches a fresh build')
results.append('C passed')

scenario('D. a gap no run covers reads as NaN, and late runs fill it')
hole = [k for k in RUNS if '2026-10-01' <= f'{ws.name_date(k):%Y-%m-%d}' <= '2026-10-10']
repo, st = new_store('D', [k for k in RUNS if k not in hole])
ds = ws.open_store(st)
nat = np.isnat(ds.forecast_reference_time.values)
# the 09-29 run ends 10-06 18Z (no 09-30 run); the 10-11 run starts 10-11 06Z
assert nat.sum() == 4 * 24 + 11
assert np.isnan(ds.Thgt.isel(time=np.where(nat)[0][0]).values).all()   # no reference: no read
print(f'   with {len(hole)} runs missing: {int(nat.sum())} uncovered steps read as NaN')
ch = us.update(repo, st, plan(RUNS))
same_as_fresh(st, RUNS, 'D')
assert not np.isnat(ws.open_store(st).forecast_reference_time.values).any()
print(f'   the late runs re-pointed {ch["repointed"]} steps; no gap left; matches a fresh build')
results.append('D passed')

scenario('E. it refuses a plan that would shorten the store')
repo, st = new_store('E', RUNS)
try:
    us.update(repo, st, plan(RUNS[:-1]))
    raise AssertionError('should have stopped')
except us.Stop as exc:
    print('   stopped:', exc)
results.append('E passed')

scenario('F. dry run writes nothing')
repo, st = new_store('F', RUNS[:-1])
head = next(iter(repo.ancestry(branch='main'))).id
ch = us.update(repo, st, plan(RUNS), dry_run=True)
assert ch['appended'] == 24 and next(iter(repo.ancestry(branch='main'))).id == head, ch
print('   reported 24 steps to append; no commit')
results.append('F passed')

shutil.rmtree(WORK)
print('\n' + '; '.join(results))
