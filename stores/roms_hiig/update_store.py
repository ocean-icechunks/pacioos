"""Daily update of the ROMS Hawaiʻi forecast best-series store (issue #4).

Each run does: read the state → diff it against what should be there → do the missing work.

  1. scan     the header of every run on Source Cooperative not yet in <workdir>/scan.jsonl
              (build_store.scan: anonymous, read-only)
  2. check    every file's structure (build_store.check); stops on anything unexpected
  3. plan     the best series from all checked runs (forecast_store.build_dataset)
  4. diff     against the store's own coordinates: a step needs (re)pointing when the store has
              no such step yet, or when its forecast_reference_time differs from the plan. The
              references of a step are a function of (run, lead) alone, because the copies are
              write-once, so the coordinates are enough to find every change.
  5. update   one commit: resize along time, set the references of the changed steps
              (IcechunkStore.set_virtual_refs, every depth plane of all 5 variables), rewrite
              time, forecast_reference_time and forecast_period, update the coverage attributes
  6. verify   reopen from storage: the coordinates equal the plan, and sampled planes of the
              changed steps equal netCDF-C reads of the files

Nothing to do → nothing is committed. A missed day is caught up on the next run, and a run that
arrives late (an older day) re-points the steps it now wins, because the plan is always made
from every run. Any run can be killed and rerun: nothing is written until the single commit.

What it will not do (it stops instead): change the start of the axis, drop a step, or turn a
covered step into an uncovered one. Those cannot happen while the copies are write-once; if one
does, a person should look (#2 covers changed files).

  python update_store.py --dest scratch --dry-run    # what would change, writes nothing
  python update_store.py --dest scratch
  python update_store.py --dest production

Needs the venv from requirements.txt and, to write, Source Cooperative keys
(source-coop login --duration 1d --port 8400, or a role in a scheduled job).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import build_store as bs  # noqa: E402
import forecast_store as fs  # noqa: E402
import pacioos_virtual as pv  # noqa: E402

log = bs.log
EPOCH = pd.Timestamp('2000-01-01')          # fs.TIME_UNITS: hours since 2000-01-01


def _hours(values) -> np.ndarray:
    """datetime64 -> float64 hours since 2000-01-01, NaT -> NaN (the stored encoding)."""
    return ((pd.DatetimeIndex(values) - EPOCH) / pd.Timedelta('1h')).to_numpy('f8', na_value=np.nan)


class Stop(RuntimeError):
    """The store is not in a state this script should touch."""


def read_state(repo) -> dict:
    """The store's time coordinates, raw (no decoding), straight from Zarr."""
    import zarr
    g = zarr.open_group(repo.readonly_session('main').store, mode='r')
    return {'time': g['time'][:], 'frt': g['forecast_reference_time'][:],
            'attrs': dict(g.attrs)}


def plan_changes(state: dict, planned) -> dict:
    """Which steps of the planned series need references written, and sanity checks."""
    t_have, f_have = state['time'], state['frt']
    t_new, f_new = _hours(planned.time.values), _hours(planned.forecast_reference_time.values)
    n_have, n_new = len(t_have), len(t_new)
    if n_new < n_have or not np.array_equal(t_new[:n_have], t_have):
        raise Stop(f'the planned axis does not extend the store\'s ({n_have} steps -> {n_new}); '
                   'a step would move or disappear')
    old = f_new[:n_have]
    lost = np.isnan(old) & ~np.isnan(f_have)
    if lost.any():
        raise Stop(f'{int(lost.sum())} covered steps would become uncovered (a run disappeared?)')
    differs = ~((old == f_have) | (np.isnan(old) & np.isnan(f_have)))
    changed = np.concatenate([np.where(differs)[0], np.arange(n_have, n_new)])
    runs_used = sorted(set(pd.DatetimeIndex(planned.forecast_reference_time.values[changed]).dropna()))
    return {'n_have': n_have, 'n_new': n_new, 'changed': changed, 'repointed': int(differs.sum()),
            'appended': n_new - n_have, 'runs': runs_used}


def apply_update(repo, planned, changes: dict, message: str) -> str:
    """One commit: resize, set the changed references, rewrite the time coordinates."""
    import icechunk
    import zarr
    session = repo.writable_session('main')
    store = session.store
    g = zarr.open_group(store, mode='r+')
    nt, changed = changes['n_new'], changes['changed']
    for name in fs.SCIENCE:
        arr = g[name]
        if arr.shape[0] != nt:
            arr.resize((nt,) + arr.shape[1:])
        m = planned[name].data.manifest
        paths, offsets, lengths = m._paths[changed], m._offsets[changed], m._lengths[changed]
        specs = []
        for j, i in enumerate(changed):
            for idx in np.ndindex(paths.shape[1:]):           # (depth, 1, 1) or (1, 1)
                p = str(paths[(j,) + idx])
                if p:
                    specs.append(icechunk.VirtualChunkSpec(
                        index=[int(i), *map(int, idx)], location=p,
                        offset=int(offsets[(j,) + idx]), length=int(lengths[(j,) + idx])))
        failed = store.set_virtual_refs(name, specs, validate_containers=True)
        if failed:
            raise RuntimeError(f'{name}: {len(failed)} references refused, e.g. {failed[:3]}')
    for name, values in (('time', _hours(planned.time.values)),
                         ('forecast_reference_time', _hours(planned.forecast_reference_time.values)),
                         ('forecast_period', planned.forecast_period.values)):
        arr = g[name]
        if arr.shape[0] != nt:
            arr.resize((nt,))
        arr[:] = np.asarray(values).astype(arr.dtype)
    now = pd.Timestamp.now('UTC')
    history = g.attrs.get('history', '')
    g.attrs.update({
        'time_coverage_start': planned.attrs['time_coverage_start'],
        'time_coverage_end': planned.attrs['time_coverage_end'],
        'forecast_runs': planned.attrs['forecast_runs'],
        'history': history + f'\n{now:%Y-%m-%dT%H:%M:%SZ} {message}',
    })
    return session.commit(message)


def verify(storage, planned, changes: dict, n_planes: int = 6) -> None:
    """Reopen from storage, as a reader: coordinates equal the plan; sampled planes = netCDF-C."""
    import netCDF4
    ds = fs.open_store(storage)
    raw = fs.open_store(storage, mask_and_scale=False)
    assert np.array_equal(ds.time.values, planned.time.values), 'time differs from the plan'
    assert np.array_equal(ds.forecast_reference_time.values.astype('M8[ns]'),
                          planned.forecast_reference_time.values.astype('M8[ns]'), equal_nan=True)
    assert np.allclose(ds.forecast_period.values, planned.forecast_period.values, equal_nan=True)
    assert ds.attrs['time_coverage_end'] == planned.attrs['time_coverage_end']
    for name in fs.SCIENCE:
        assert ds[name].shape[0] == len(planned.time)
    changed = changes['changed']
    picks = sorted({int(changed[0]), int(changed[-1])}
                   | {int(i) for i in np.random.default_rng(0).choice(changed, min(n_planes, len(changed)), replace=False)})
    frt = pd.DatetimeIndex(ds.forecast_reference_time.values)
    n = 0
    for i in picks:
        if pd.isna(frt[i]):
            continue
        lead = int(ds.forecast_period.values[i]) // 3
        with netCDF4.Dataset(fs.URL_PREFIX + fs.key(frt[i]) + '#mode=bytes') as nc:
            for name, k in (('temp', 0), ('u', 20), ('zeta', None)):
                v = nc[name]
                v.set_auto_maskandscale(False)
                exp = v[lead] if k is None else v[lead, k]
                got = raw[name].isel({'time': i} | ({} if k is None else {'depth': k})).values
                assert np.array_equal(got, exp), (str(ds.time.values[i]), name, k)
                n += 1
    log(f'  verified from storage: coordinates = plan ({len(planned.time)} steps); '
        f'{n} planes of changed steps = netCDF-C')


def update(repo, storage, planned, dry_run: bool = False) -> dict | None:
    """Diff the store against `planned` and apply the difference. Returns the change summary."""
    state = read_state(repo)
    changes = plan_changes(state, planned)
    if not len(changes['changed']):
        log(f'  up to date: {changes["n_have"]} steps to {planned.attrs["time_coverage_end"]}; nothing committed')
        return None
    runs = ', '.join(f'{r:%Y-%m-%d}' for r in changes['runs'])
    message = (f'daily update: {changes["appended"]} steps appended, {changes["repointed"]} re-pointed, '
               f'from runs {runs}; now {planned.attrs["forecast_runs"]}')
    log(f'  {message}')
    if dry_run:
        log('  dry run: nothing written')
        return changes
    t0 = time.perf_counter()
    snap = apply_update(repo, planned, changes, message)
    log(f'  committed {snap} in {time.perf_counter() - t0:.1f}s')
    verify(storage, planned, changes)
    return changes


def main():
    import icechunk
    import warnings
    warnings.simplefilter('ignore')
    icechunk.set_logs_filter('error')
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--dest', choices=sorted(bs.DESTINATIONS), default='scratch')
    ap.add_argument('--workdir', type=Path, default=HERE / 'out')
    ap.add_argument('--procs', type=int, default=4)
    ap.add_argument('--dry-run', action='store_true', help='report what would change; write nothing')
    a = ap.parse_args()
    a.workdir.mkdir(parents=True, exist_ok=True)
    log(f'update: {bs.BUCKET}/{bs.DESTINATIONS[a.dest]}' + (' (PRODUCTION)' if a.dest == 'production' else ''))
    bs.scan(a.workdir, a.procs)
    planned, runs, _ = bs.planned_dataset(a.workdir)
    repo, time_left = bs.open_destination(a.dest)
    log(f'  keys valid for {time_left}')
    if bs._written(repo) is None:
        sys.exit('  the store is empty: build it first with build_store.py write')
    storage = icechunk.http_storage(f'{bs.PUBLIC}/{bs.BUCKET}/{bs.DESTINATIONS[a.dest]}')
    try:
        update(repo, storage, planned, dry_run=a.dry_run)
    except Stop as exc:
        sys.exit(f'  stopped: {exc}')
    log('update: done')


if __name__ == '__main__':
    main()
