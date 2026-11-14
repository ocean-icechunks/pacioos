"""Tests of update_store.py against local Icechunk repos (no credentials; reads the public copies).

Each scenario builds a store from a subset of the runs, applies update_store.update with the
plan for more runs, and checks the result against a fresh full build of that plan, read back
from storage. Needs the header scan in out/scan.jsonl (python build_store.py scan).

  python test_update_store.py        # about 2 minutes
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

import build_store as bs  # noqa: E402
import forecast_store as fs  # noqa: E402
import pacioos_virtual as pv  # noqa: E402
import update_store as us  # noqa: E402

icechunk.set_logs_filter('error')
RECS = bs.load_scan(HERE / 'out')
RUNS = sorted(RECS)
REF = pv.scan_nc3(fs.key(RUNS[0]))
MAIN, SSH, _ = fs.load_metadata()
VA = fs.variable_attrs(MAIN, SSH, REF['vars']['mask']['attrs'])
WORK = Path(tempfile.mkdtemp(prefix='pacioos-update-test-'))


def plan(days):
    return fs.build_dataset(bs._scans_for(RECS, list(days), REF), VA, MAIN)


def new_store(name, days):
    storage = icechunk.local_filesystem_storage(str(WORK / name))
    repo = icechunk.Repository.create(storage, config=fs.repository_config(),
                                      authorize_virtual_chunk_access=pv.reader_authorization())
    repo.save_config()
    s = repo.writable_session('main')
    plan(days).vz.to_icechunk(s.store)
    s.commit(f'initial: {len(days)} runs')
    return repo, storage


def same_as_fresh(storage, days, name):
    """The updated store reads exactly like a fresh build of the same runs (refs compared via data)."""
    fresh_repo, fresh_storage = new_store(name + '-fresh', days)
    a, b = fs.open_store(storage, mask_and_scale=False), fs.open_store(fresh_storage, mask_and_scale=False)
    for c in ('time', 'forecast_reference_time', 'forecast_period'):
        assert np.array_equal(a[c].values, b[c].values, equal_nan=True), c
    assert dict(a.sizes) == dict(b.sizes)
    # zeta at one water point over the last 120 steps: one reference per step, cheap to read
    pt = dict(lat=100, lon=150)
    assert np.array_equal(a.zeta.isel(time=slice(-120, None), **pt).values,
                          b.zeta.isel(time=slice(-120, None), **pt).values, equal_nan=True)


def scenario(title):
    print(f'\n=== {title}', flush=True)


results = []

scenario('A. three missed days are caught up; a rerun commits nothing')
days = RUNS[:-3]
repo, st = new_store('A', days)
before = next(iter(repo.ancestry(branch='main'))).id
ch = us.update(repo, st, plan(RUNS))
print(f'   appended {ch["appended"]}, re-pointed {ch["repointed"]}')
assert ch['appended'] == 3 * 8
# the old store ended 7 days after its last run; the first new run takes over from its own start
assert days[-1] == '2026-11-09' and ch['repointed'] == 6 * 8 + 1, ch['repointed']
same_as_fresh(st, RUNS, 'A')
assert us.update(repo, st, plan(RUNS)) is None
r = icechunk.Repository.open(st, authorize_virtual_chunk_access=pv.reader_authorization())
import xarray as xr  # noqa: E402
prev = xr.open_zarr(r.readonly_session(snapshot_id=before).store, consolidated=False, chunks=None)
assert prev.sizes['time'] == plan(days).sizes['time'], 'the previous snapshot changed'
print('   matches a fresh build; rerun: nothing committed; the previous snapshot still has '
      f'{prev.sizes["time"]} steps')
results.append('A passed')

scenario('B. a run that arrives late re-points only the steps it now wins')
late = '2026-11-05'
repo, st = new_store('B', [d for d in RUNS if d != late])
ch = us.update(repo, st, plan(RUNS))
assert ch['appended'] == 0 and ch['repointed'] == 8, ch
assert [f'{r:%Y-%m-%d}' for r in ch['runs']] == [late]
same_as_fresh(st, RUNS, 'B')
print('   8 steps re-pointed to the late run, nothing appended; matches a fresh build')
results.append('B passed')

scenario('C. a gap no run covers reads as NaN, and a late run fills it')
hole = [d for d in RUNS if '2026-10-20' <= d <= '2026-10-29']
upto = [d for d in RUNS if d <= '2026-11-12' and d not in hole]
repo, st = new_store('C', upto)
ds = fs.open_store(st)
nat = np.isnat(ds.forecast_reference_time.values)
assert nat.sum() > 0 and np.isnan(ds.zeta.isel(time=np.where(nat)[0][0]).values).all()
print(f'   with {len(hole)} runs missing: {int(nat.sum())} uncovered steps read as NaN')
ch = us.update(repo, st, plan(RUNS))
same_as_fresh(st, RUNS, 'C')
assert not np.isnat(fs.open_store(st).forecast_reference_time.values).any()
print(f'   the late runs re-pointed {ch["repointed"]} steps; no gap left; matches a fresh build')
results.append('C passed')

scenario('D. it refuses a plan that would shorten the store')
repo, st = new_store('D', RUNS)
try:
    us.update(repo, st, plan(RUNS[:-1]))
    raise AssertionError('should have stopped')
except us.Stop as exc:
    print('   stopped:', exc)
results.append('D passed')

scenario('E. dry run writes nothing')
repo, st = new_store('E', RUNS[:-1])
head = next(iter(repo.ancestry(branch='main'))).id
ch = us.update(repo, st, plan(RUNS), dry_run=True)
assert ch['appended'] == 8 and next(iter(repo.ancestry(branch='main'))).id == head
print('   reported 8 steps to append; no commit')
results.append('E passed')

shutil.rmtree(WORK)
print('\n' + '; '.join(results))
