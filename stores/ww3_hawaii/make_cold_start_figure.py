"""Draw the README's cold-start figure from the published store.

Significant wave height at one point, 2026-10-10 .. 2026-11-18, with the steps flagged
`cold_start_run` shaded. Writes `cold_starts_2026.png` beside this script.

    python make_cold_start_figure.py
"""
from pathlib import Path

import icechunk
import matplotlib
import numpy as np
import pandas as pd
import xarray as xr
import zarr

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

URL = 'https://data.source.coop/ocean-icechunks/pacioos/ww3_hawaii/icechunk'
POINT = dict(lat=20.5, lon=202.5)          # open sea between Maui and Hawaiʻi Island
SPAN = slice('2026-10-10', '2026-11-18T18:00')


def main():
    zarr.config.set({'async.concurrency': 128})
    repo = icechunk.Repository.open(icechunk.http_storage(URL))
    auth = {p: icechunk.credentials.HttpAccess for p in repo.config.virtual_chunk_containers or []}
    repo = repo.reopen(authorize_virtual_chunk_access=auth)
    ds = xr.open_zarr(repo.readonly_session('main').store, consolidated=False, chunks=None)

    s = ds.Thgt.sel(time=SPAN).sel(POINT, method='nearest').load()
    t = pd.DatetimeIndex(s.time.values)
    cold = (s.best_step_flag.values & 1) > 0
    runs = pd.DatetimeIndex(s.forecast_reference_time.values)

    fig, ax = plt.subplots(figsize=(10, 3.6), dpi=120)
    # Shade each contiguous block of cold-start steps.
    edges = np.flatnonzero(np.diff(np.r_[0, cold.astype(int), 0]))
    for a, b in zip(edges[::2], edges[1::2]):
        ax.axvspan(t[a], t[b - 1] + pd.Timedelta('1h'), color='#f2c14e', alpha=0.35, lw=0)
    ax.plot(t, s.values, color='#1f4e79', lw=1.2)
    for r in sorted({r for r, c in zip(runs, cold) if c}):
        ax.axvline(r, color='#b5651d', lw=0.8, ls=':')
        ax.text(r, np.nanmax(s.values) * 1.02, r.strftime('%m-%d'),
                rotation=90, va='bottom', ha='right', fontsize=7, color='#b5651d')
    ax.set_ylabel('Thgt, significant wave height (m)')
    ax.set_title(f'WW3 best series at {float(s.lat):.2f}°N {float(s.lon):.2f}°E (= '
                 f'{float(s.lon) - 360:.2f}°): shaded steps are flagged cold_start_run',
                 fontsize=9)
    ax.set_ylim(0, np.nanmax(s.values) * 1.15)
    ax.margins(x=0)
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    out = Path(__file__).with_name('cold_starts_2026.png')
    fig.savefig(out)
    print(out, f'{cold.sum()} of {len(cold)} steps flagged; cold-start runs:',
          [r.strftime('%Y-%m-%d') for r in sorted({r for r, c in zip(runs, cold) if c})])


if __name__ == '__main__':
    main()
