"""Exercise real Icechunk/NetCDF reads against a tiny local HTTP range server only."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch

import icechunk
import netCDF4
import numpy as np
import pandas as pd
import xarray as xr
from xarray.backends.zarr import FillValueCoder
import zarr

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'stores')]
import pacioos_virtual as pv
from validation import verify_snapshot


class RangeHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        requested = self.headers.get('Range')
        if not requested:
            return super().do_GET()
        filename = Path(self.translate_path(self.path))
        size = filename.stat().st_size
        start, end = requested.removeprefix('bytes=').split('-')
        start, end = int(start), min(int(end) if end else size - 1, size - 1)
        self.send_response(206)
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Accept-Ranges', 'bytes')
        self.end_headers()
        with filename.open('rb') as source:
            source.seek(start)
            self.wfile.write(source.read(end - start + 1))


class LocalStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(RangeHandler, directory=str(cls.root)))
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.prefix = f'http://127.0.0.1:{cls.server.server_port}/'
        cls.url_patch = patch.object(pv, 'URL_PREFIX', cls.prefix)
        cls.url_patch.start()
        filename = cls.root / 'run.nc'
        with netCDF4.Dataset(filename, 'w', format='NETCDF3_CLASSIC') as nc:
            for name, length in [('time', None), ('depth', 1), ('lat', 2), ('lon', 3)]:
                nc.createDimension(name, length)
            time = nc.createVariable('time', 'f8', ('time',))
            time.units = 'hours since 2026-11-17'
            time[:] = [0, 24, 48]
            for name, values in [('depth', [0]), ('lat', [20, 21]), ('lon', [200, 201, 202])]:
                nc.createVariable(name, 'f4', (name,))[:] = values
            value = nc.createVariable('temp', 'f4', ('time', 'depth', 'lat', 'lon'), fill_value=-9999.)
            values = np.arange(18, dtype='f4').reshape(3, 1, 2, 3)
            values[:, 0, 0, 0] = -9999
            value[:] = values
        scan = pv.scan_nc3('run.nc')
        times = scan['time']
        best = pd.DataFrame({'run': [0, 0, 0], 'lead': [0, 1, 2]}, index=times)
        variable = pv.manifest_variable('temp', [scan], best, ('time', 'depth', 'lat', 'lon'),
                                        {'_FillValue': FillValueCoder.encode(-9999., np.dtype('f4'))},
                                        fill_value=-9999.)
        cls.planned = xr.Dataset({'temp': variable}, coords={
            'time': times, 'depth': [0.], 'lat': [20., 21.], 'lon': [200., 201., 202.],
            'forecast_reference_time': ('time', np.repeat(times.values[0], 3)),
            'forecast_period': ('time', np.array([0, 24, 48], dtype='f4')),
        }, attrs={'time_coverage_start': '2026-11-17T00:00:00Z',
                  'time_coverage_end': '2026-11-19T00:00:00Z', 'forecast_runs': 'one fixture run'})
        for name in ('time', 'forecast_reference_time'):
            cls.planned[name].encoding = {'units': 'hours since 2026-11-17', 'dtype': 'float64'}
        cls.storage = icechunk.local_filesystem_storage(str(cls.root / 'store'))
        cls.repo = icechunk.Repository.create(cls.storage, config=pv.repository_config(100),
                                              authorize_virtual_chunk_access=pv.reader_authorization())
        cls.repo.save_config()
        session = cls.repo.writable_session('main')
        cls.planned.vz.to_icechunk(session.store)
        cls.snapshot = session.commit('local fixture')
        cls.config = dict(verify_lookback_days=3, max_run_age_hours=72, verify_samples=4)

    @classmethod
    def tearDownClass(cls):
        cls.url_patch.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temporary.cleanup()

    def test_recent_reads_real_planes_and_decodes_fill(self):
        result = verify_snapshot(self.storage, self.planned, self.snapshot, 'recent',
                                 self.config, '2026-11-18T00:00:00Z')
        self.assertEqual(result['planes'], 3)

    def test_full_audit_reads_and_compares_history(self):
        result = verify_snapshot(self.storage, self.planned, self.snapshot, 'full',
                                 self.config, '2026-11-18T00:00:00Z')
        self.assertEqual(result['coordinates_checked'], 3)

    def test_normal_validation_does_not_read_nonincoming_source_files(self):
        result = verify_snapshot(self.storage,self.planned,self.snapshot,'recent',self.config,
                                 '2026-11-18',only_sources=[self.prefix+'another-run.nc'])
        self.assertEqual(result['planes'],0)
        self.assertEqual(result['data_scope'],'incoming_sources')

    def test_broken_new_snapshot_fails_but_original_snapshot_still_passes(self):
        session = self.repo.writable_session('main')
        zarr.open_group(session.store, mode='r+')['temp'][1, 0, 1, 1] = 999
        broken = session.commit('deliberately corrupt scratch fixture')
        with self.assertRaisesRegex(AssertionError, 'plane differs'):
            verify_snapshot(self.storage, self.planned, broken, 'recent', self.config, '2026-11-18')
        verify_snapshot(self.storage, self.planned, self.snapshot, 'recent', self.config, '2026-11-18')


if __name__ == '__main__':
    unittest.main()
