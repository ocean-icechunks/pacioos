"""Read-only, snapshot-pinned recent validation and archive-wide sampled audits."""
from __future__ import annotations

from contextlib import ExitStack

import numpy as np
import pandas as pd


def scope_indices(planned, scope, now, lookback_days, max_run_age_hours):
    times = pd.DatetimeIndex(planned.time.values)
    origins = pd.DatetimeIndex(planned.forecast_reference_time.values)
    if not len(times) or times.hasnans or times.has_duplicates or not times.is_monotonic_increasing:
        raise ValueError('Invalid planned time axis')
    now = pd.Timestamp(now).tz_localize(None) if pd.Timestamp(now).tzinfo else pd.Timestamp(now)
    if scope == 'full':
        return np.arange(len(times))
    newest = origins.dropna().max()
    if pd.isna(newest) or now - newest > pd.Timedelta(hours=max_run_age_hours):
        raise ValueError('Newest forecast run is stale; check source availability')
    if times[-1] < now:
        raise ValueError('Forecast coverage ends before this job started')
    indices = np.flatnonzero(times >= now - pd.Timedelta(days=lookback_days))
    if not len(indices) or not ((times[indices] <= now) & ~origins[indices].isna()).any():
        raise ValueError('Recent window has no covered historical data')
    return indices


def sample_indices(planned, indices, scope, budget):
    """Bound routine reads; full audits sample every month and flagged transition."""
    times = pd.DatetimeIndex(planned.time.values)
    origins = pd.DatetimeIndex(planned.forecast_reference_time.values)
    first, last = int(indices[0]), int(indices[-1])
    if scope == 'full':
        picks = {first, last}
        for month in sorted(set(times.to_period('M'))):
            matching = np.flatnonzero((times.to_period('M') == month) & ~origins.isna())
            if len(matching):
                picks.add(int(matching[len(matching) // 2]))
        if 'best_step_flag' in planned:
            flags = planned.best_step_flag.values
            for i in np.flatnonzero(flags[1:] != flags[:-1]) + 1:
                picks.update([int(i - 1), int(i)])
        # Include the edges of all uncovered periods.
        missing = origins.isna()
        for i in np.flatnonzero(missing[1:] != missing[:-1]) + 1:
            picks.update([int(i - 1), int(i)])
        return sorted(picks)
    count = min(max(budget, 4), len(indices))
    newest = origins.dropna().max()
    newest_steps = indices[origins[indices] == newest]
    picks = {first, last}
    if len(newest_steps):
        picks.add(int(newest_steps[0]))
    # Distribute reads across the entire past-plus-forecast window, then fill gaps.
    for i in indices[np.linspace(0, len(indices) - 1, count, dtype=int)]:
        if len(picks) >= count:
            break
        picks.add(int(i))
    transitions = [int(i) for i in indices[1:] if origins[i] != origins[i - 1]]
    for i in transitions:
        if len(picks) >= count:
            break
        picks.add(i)
    return sorted(picks)


def compare_coordinates(ds, planned, indices, names):
    for name in names:
        a, b = ds[name].values[indices], planned[name].values[indices]
        if np.issubdtype(b.dtype, np.datetime64):
            a, b = a.astype('M8[ns]'), b.astype('M8[ns]')
        if not np.array_equal(a, b, equal_nan=np.issubdtype(b.dtype, np.inexact)
                              or np.issubdtype(b.dtype, np.datetime64)):
            raise AssertionError(f'{name}: coordinates differ from the source plan')


def verify_snapshot(storage, planned, snapshot, scope, cfg, now, only_sources=None):
    import icechunk
    import netCDF4
    import xarray as xr
    import zarr
    import best_series_update as bsu
    import pacioos_virtual as pv

    indices = scope_indices(planned, scope, now, cfg['verify_lookback_days'], cfg['max_run_age_hours'])
    science = bsu.gridded(planned)
    if only_sources is None:
        data_indices = indices
    else:
        allowed = set(only_sources)
        data_indices = np.asarray([i for i in indices if any(
            str(planned[name].data.manifest._paths[(i,) + (0,) * (planned[name].data.manifest._paths.ndim - 1)])
            in allowed for name in science)], dtype=int)
    picks = sample_indices(planned, data_indices, scope, cfg['verify_samples']) if len(data_indices) else []
    zarr.config.set({'async.concurrency': 32})

    def open_reader(mask_and_scale):
        repo = icechunk.Repository.open(storage)
        prefixes = set(repo.config.virtual_chunk_containers or {})
        if prefixes != {pv.URL_PREFIX}:
            raise AssertionError('Persisted virtual prefixes differ from the configured source root')
        repo = repo.reopen(authorize_virtual_chunk_access=pv.reader_authorization())
        return xr.open_zarr(repo.readonly_session(snapshot_id=snapshot).store,
                            consolidated=False, chunks=None, mask_and_scale=mask_and_scale)

    ds = bsu.retry(lambda: open_reader(True), 'open public snapshot')
    raw = bsu.retry(lambda: open_reader(False), 'open raw public snapshot')
    source_handles = ExitStack()
    opened_sources = {}
    try:
        if dict(ds.sizes) != dict(planned.sizes):
            raise AssertionError('Published dimensions differ from the plan')
        for attr in ('time_coverage_start', 'time_coverage_end', 'forecast_runs'):
            if ds.attrs.get(attr) != planned.attrs[attr]:
                raise AssertionError(f'{attr}: published metadata differs from the plan')
        compare_coordinates(ds, planned, indices, bsu.time_coords(planned))
        metadata_repo = icechunk.Repository.open(storage).reopen(
            authorize_virtual_chunk_access=pv.reader_authorization())
        metadata_session = metadata_repo.readonly_session(snapshot_id=snapshot)
        group = zarr.open_group(metadata_session.store, mode='r')
        for name in science:
            if ds[name].dims != planned[name].dims or ds[name].dtype.kind != planned[name].dtype.kind:
                raise AssertionError(f'{name}: dimensions or dtype differ')
            if ds[name].dtype.itemsize != planned[name].dtype.itemsize:
                raise AssertionError(f'{name}: dtype size differs')
            expected_metadata = planned[name].data.metadata
            actual_metadata = group[name].metadata
            if (actual_metadata.chunk_grid != expected_metadata.chunk_grid
                    or actual_metadata.codecs != expected_metadata.codecs):
                raise AssertionError(f'{name}: chunk grid or codecs differ')
        if scope == 'full':
            from virtualizarr.manifests import ManifestArray
            expected_locations = set()
            for variable in planned.variables.values():
                if isinstance(variable.data, ManifestArray):
                    expected_locations.update(str(p) for p in np.unique(variable.data.manifest._paths) if str(p))
            if set(metadata_session.all_virtual_chunk_locations()) != expected_locations:
                raise AssertionError('Committed virtual source locations differ from the complete plan')
            for name in planned.coords:
                if planned[name].dims != ('time',):
                    np.testing.assert_array_equal(ds[name].values, planned[name].values, err_msg=name)
        planes = 0
        for i in picks:
            timestamp = pd.Timestamp(planned.time.values[i])
            for name in science:
                manifest = planned[name].data.manifest
                depth = i % manifest._paths.shape[1] if manifest._paths.ndim == 4 else None
                index = (i, depth, 0, 0) if depth is not None else (i, 0, 0)
                source = str(manifest._paths[index])
                selection = {'time': i} | ({'depth': depth} if depth is not None else {})

                def check_plane():
                    if not source:
                        if not np.isnan(ds[name].isel(selection).values).all():
                            raise AssertionError(f'{name}: uncovered step is not missing at {timestamp}')
                        return
                    if source not in opened_sources:
                        opened_sources[source] = source_handles.enter_context(netCDF4.Dataset(source + '#mode=bytes'))
                    nc = opened_sources[source]
                    lead = np.flatnonzero(pv._decode_time(nc['time'][:], nc['time'].units) == timestamp)
                    if len(lead) != 1:
                        raise AssertionError('Source has no unique matching time')
                    variable = nc[name]
                    variable.set_auto_maskandscale(False)
                    k = depth if depth is not None else 0
                    expected = variable[int(lead[0]), k] if variable.ndim == 4 else variable[int(lead[0])]
                    got = raw[name].isel(selection).values
                    if not np.array_equal(got, np.asarray(expected).reshape(got.shape)):
                        raise AssertionError(f'{name}: plane differs from netCDF-C at {timestamp}')
                    variable.set_auto_maskandscale(True)
                    decoded = variable[int(lead[0]), k] if variable.ndim == 4 else variable[int(lead[0])]
                    expected = np.ma.filled(decoded, np.nan).reshape(got.shape)
                    if not np.array_equal(ds[name].isel(selection).values, expected, equal_nan=True):
                        raise AssertionError(f'{name}: decoded values differ at {timestamp}')
                bsu.retry(check_plane, f'verify {name} {timestamp}')
                planes += 1
        result = dict(snapshot=snapshot, scope=scope, coordinates_checked=len(indices),
                      sample_times=[str(planned.time.values[i]) for i in picks], planes=planes,
                      data_scope='incoming_sources' if only_sources is not None else scope,
                      start=str(planned.time.values[indices[0]]), end=str(planned.time.values[indices[-1]]))
        print(f'Validated {scope}: {len(indices)} steps, {planes} sampled planes, snapshot {snapshot}', flush=True)
        return result
    finally:
        source_handles.close()
        ds.close()
        raw.close()
