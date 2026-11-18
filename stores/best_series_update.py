"""Update a published best-series store in place: the shared part of each product's update_store.py.

Issue #4. Each run does: read the state → diff it against what should be there → do the missing
work. The product's update_store.py scans and checks new files and plans the whole best series
(its build_store.planned_dataset); this module does the rest, the same way for every product:

  diff     the plan against the store's own coordinates: a step needs (re)pointing when the
           store has no such step yet, or when its forecast_reference_time differs from the plan.
           A step's references are a function of (run, lead) alone, because the copies are
           write-once, so the coordinates are enough to find every change.
  update   one commit: resize along time, set the references of the changed steps
           (IcechunkStore.set_virtual_refs, every plane of every gridded variable), rewrite every
           coordinate on time (time, forecast_reference_time, forecast_period, and e.g. WW3's
           best_step_flag), update the coverage attributes and history
  verify   reopen from storage, as a reader: the time coordinates equal the plan, and sampled
           planes of the changed steps equal netCDF-C reads of the files they point at, with the
           lead found from the file's own time variable

What it reads from the plan and the store, so nothing here is product-specific: the gridded
variables are the planned variables with a chunk manifest on time; the time coordinates are the
planned 1-D variables on time; datetimes are encoded with the units saved on the store's arrays.

Nothing to do → nothing is committed. A missed day is caught up on the next run, and a run that
arrives late (an older day) re-points the steps it now wins, because the plan is always made
from every run. Any run can be killed and rerun: nothing is written until the single commit.

What it will not do (it stops instead): change the start of the axis, drop a step, or turn a
covered step into an uncovered one. Those cannot happen while the copies are write-once; if one
does, a person should look (#2 covers changed files).
"""
from __future__ import annotations

import time
from typing import Callable

import numpy as np
import pandas as pd

from email_notifications import try_email_error
import pacioos_virtual as pv


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def notify_update_error(error: BaseException, description: str, dest: str,
                        script_filepath: str) -> None:
    """Add product and destination context to a shared error notification."""
    try_email_error(
        script_filepath, error, subject_add=f'({dest})',
        message_add=f'Product: {description}\nDestination: {dest}',
    )


class Stop(RuntimeError):
    """The store is not in a state this script should touch."""


def retry(fn, what: str, attempts: int = 4, wait: float = 10.0):
    """fn(), retried on read errors. Source Cooperative resets connections now and then under
    load ("Connection reset by peer", short bodies), which is not a wrong value: an
    AssertionError (a real mismatch) is never retried."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except AssertionError:
            raise
        except Exception as exc:                                   # noqa: BLE001
            if attempt == attempts:
                raise
            log(f'  {what}: {type(exc).__name__} ({str(exc).splitlines()[0][:120]}); '
                f'retry {attempt}/{attempts - 1} in {wait * attempt:.0f}s')
            time.sleep(wait * attempt)


# ------------------------------------------------------------------ what the plan holds

def gridded(planned) -> list[str]:
    """The variables whose data are references (a chunk manifest), with time first."""
    from virtualizarr.manifests import ManifestArray
    return [n for n in planned.data_vars
            if isinstance(planned[n].data, ManifestArray) and planned[n].dims[0] == 'time']


def time_coords(planned) -> list[str]:
    """Every 1-D variable on time: time, forecast_reference_time, forecast_period, flags, ..."""
    return [n for n in planned.variables if planned[n].dims == ('time',)]


def encode_time(values, units: str) -> np.ndarray:
    """datetime64 -> float64 in `units` ("hours|minutes since ..."), NaT -> NaN: the stored encoding."""
    unit, since = units.split(' since ')
    t0 = pd.Timestamp(since.replace(' UTC', ''))
    step = pd.Timedelta(1, {'hours': 'h', 'minutes': 'min'}[unit])
    return ((pd.DatetimeIndex(values) - t0) / step).to_numpy('f8', na_value=np.nan)


# ------------------------------------------------------------------ diff

def read_state(repo) -> dict:
    """The store's time and forecast_reference_time, raw (no decoding), with their units."""
    import zarr
    g = zarr.open_group(repo.readonly_session('main').store, mode='r')
    return {'time': g['time'][:], 'frt': g['forecast_reference_time'][:],
            'units': g['time'].attrs['units'], 'frt_units': g['forecast_reference_time'].attrs['units'],
            'attrs': dict(g.attrs)}


def plan_changes(state: dict, planned) -> dict:
    """Which steps of the planned series need references written, and sanity checks."""
    t_have, f_have = state['time'], state['frt']
    t_new = encode_time(planned.time.values, state['units'])
    f_new = encode_time(planned.forecast_reference_time.values, state['frt_units'])
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


# ------------------------------------------------------------------ update

def apply_update(repo, planned, changes: dict, message: str) -> str:
    """One commit: resize, set the changed references, rewrite the time coordinates."""
    import icechunk
    import zarr
    session = repo.writable_session('main')
    store = session.store
    g = zarr.open_group(store, mode='r+')
    nt, changed = changes['n_new'], changes['changed']
    for name in gridded(planned):
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
    for name in time_coords(planned):
        arr = g[name]
        values = planned[name].values
        if np.issubdtype(values.dtype, np.datetime64):
            values = encode_time(values, arr.attrs['units'])
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


# ------------------------------------------------------------------ verify

def verify(storage, planned, changes: dict, open_store: Callable, n_steps: int = 6) -> None:
    """Reopen from storage, as a reader: coordinates = plan; sampled planes of changed steps = netCDF-C.

    For each sampled step and variable, the file is the one the plan points at, but the lead is
    found from the file's own time variable (netCDF-C), and the plane compared is read by
    netCDF-C, so a wrong offset or a wrong lead would show.
    """
    import netCDF4
    ds = retry(lambda: open_store(storage), 'open the store')
    raw = retry(lambda: open_store(storage, mask_and_scale=False), 'open the store')
    for name in time_coords(planned):
        a, b = ds[name].values, planned[name].values
        if np.issubdtype(b.dtype, np.datetime64):
            a, b = a.astype('M8[ns]'), b.astype('M8[ns]')
        assert np.array_equal(a, b, equal_nan=np.issubdtype(b.dtype, np.inexact)
                              or np.issubdtype(b.dtype, np.datetime64)), f'{name} differs from the plan'
    assert ds.attrs['time_coverage_end'] == planned.attrs['time_coverage_end']
    names = gridded(planned)
    for name in names:
        assert ds[name].shape[0] == len(planned.time), name
    changed = changes['changed']
    rng = np.random.default_rng(0)
    picks = sorted({int(changed[0]), int(changed[-1])}
                   | {int(i) for i in rng.choice(changed, min(n_steps, len(changed)), replace=False)})
    n = 0
    for i in picks:
        t_i = pd.Timestamp(ds.time.values[i])
        planes = {}                                           # name -> (k, path): one plane each
        for name in names:
            m = planned[name].data.manifest
            k = int(rng.integers(m._paths.shape[1])) if m._paths.ndim == 4 else 0
            planes[name] = (k, str(m._paths[(i, k, 0, 0) if m._paths.ndim == 4 else (i, 0, 0)]))
        paths = {p for _, p in planes.values()}
        assert len(paths) == 1, (str(t_i), paths)             # one step, one run, one file
        path = paths.pop()
        if not path:                                          # an uncovered step: nothing to read
            continue

        def check_step():
            with netCDF4.Dataset(path + '#mode=bytes') as nc:
                lead = int(np.where(pv._decode_time(nc['time'][:], nc['time'].units) == t_i)[0][0])
                for name, (k, _) in planes.items():
                    v = nc[name]
                    v.set_auto_maskandscale(False)
                    exp = v[lead, k] if v.ndim == 4 else v[lead]  # WW3: (time, z=1, lat, lon) -> k = 0
                    got = raw[name].isel({'time': i} | ({'depth': k} if raw[name].ndim == 4 else {})).values
                    assert np.array_equal(got, np.asarray(exp).reshape(got.shape)), (str(t_i), name, k)
            return len(planes)
        n += retry(check_step, f'verify {t_i:%Y-%m-%dT%HZ}')
    log(f'  verified from storage: coordinates = plan ({len(planned.time)} steps); '
        f'{n} planes of {len(picks)} changed steps = netCDF-C')


# ------------------------------------------------------------------ the whole update

def update(repo, storage, planned, open_store: Callable, dry_run: bool = False) -> dict | None:
    """Diff the store against `planned` and apply the difference. Returns the change summary."""
    state = retry(lambda: read_state(repo), 'read the store')
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
    verify(storage, planned, changes, open_store)
    return changes


def main(description: str, bs, open_store: Callable, default_procs: int = 4) -> None:
    """Command line for a product: `bs` is its build_store module (scan, planned_dataset, ...)."""
    import argparse
    import sys
    import warnings
    from pathlib import Path

    import icechunk
    warnings.simplefilter('ignore')
    icechunk.set_logs_filter('error')
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument('--dest', choices=sorted(bs.DESTINATIONS), default='scratch')
    ap.add_argument('--workdir', type=Path, default=Path(bs.HERE) / 'out')
    ap.add_argument('--procs', type=int, default=default_procs)
    ap.add_argument('--dry-run', action='store_true', help='report what would change; write nothing')
    a = ap.parse_args()
    try:
        a.workdir.mkdir(parents=True, exist_ok=True)
        log(f'update: {bs.BUCKET}/{bs.DESTINATIONS[a.dest]}' +
            (' (PRODUCTION)' if a.dest == 'production' else ''))
        bs.scan(a.workdir, a.procs)
        planned = bs.planned_dataset(a.workdir)[0]
        repo, time_left = bs.open_destination(a.dest)
        log(f'  keys valid for {time_left}')
        if bs._written(repo) is None:
            sys.exit('  the store is empty: build it first with build_store.py write')
        storage = icechunk.http_storage(f'{bs.PUBLIC}/{bs.BUCKET}/{bs.DESTINATIONS[a.dest]}')
        update(repo, storage, planned, open_store, dry_run=a.dry_run)
    except Stop as exc:
        notify_update_error(exc, description, a.dest, sys.argv[0])
        sys.exit(f'  stopped: {exc}')
    except SystemExit as exc:
        if exc.code not in (None, 0):
            notify_update_error(exc, description, a.dest, sys.argv[0])
        raise
    except Exception as exc:
        notify_update_error(exc, description, a.dest, sys.argv[0])
        raise
    log('update: done')
