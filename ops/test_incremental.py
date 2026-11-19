"""Regression checks: routine runs must never turn into historical verification."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from common import atomic_json, read_json
import headers
import pipeline
from validation import sample_indices


class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.work = self.root / 'headers'
        self.work.mkdir()
        self.cfg = dict(bucket='bucket', prefix='pacioos', install_root=str(self.root), state_dir=str(self.root / 'state'), scan_processes=2,
                        datasets={'roms_hiig': {'update_store': True}})
        self.old = 'pacioos/roms_hiig/netcdf/2026/hiig_forec_20261117.nc'
        self.new = 'pacioos/roms_hiig/netcdf/2026/hiig_forec_20261118.nc'
        self.objects = {self.old: dict(size=1, etag='old'), self.old+'.md5': dict(size=32, etag='side')}

    def model_and_builder(self):
        model = types.SimpleNamespace(DATASET='roms_hiig',
            key=lambda run: f'roms_hiig/netcdf/2026/hiig_forec_{pd.Timestamp(run):%Y%m%d}.nc',
            list_runs=Mock(side_effect=AssertionError('No extra remote listings allowed')))
        records = {'2026-11-17': {'day': '2026-11-17', 'key': model.key('2026-11-17')}}
        (self.work/'scan.jsonl').write_text(json.dumps(records['2026-11-17'])+'\n')
        builder = Mock()
        builder.load_scan.side_effect = lambda work: records
        return model, builder, records

    def test_no_transfers_does_not_open_store_scan_headers_or_verify_data(self):
        atomic_json(self.root/'baseline-copies.json', {self.old: pipeline.copy_identity(self.objects,self.old)})
        with patch('pipeline.upload', return_value=set()), patch('pipeline.inventory', return_value=self.objects), \
             patch('pipeline.modules', side_effect=AssertionError('Historical planning must not run')), \
             patch('pipeline.verify_copies') as copies, patch('pipeline.finish_validation') as validate:
            pipeline.process(self.cfg, 'roms_hiig', self.root, 'sync', 'recent', False)
        copies.assert_not_called()
        validate.assert_not_called()
        self.assertTrue(read_json(self.root/'last-success-sync.json')['no_new_transfers'])

    def test_previously_acknowledged_transfers_are_not_verified_again(self):
        objects={**self.objects,self.new:dict(size=2),self.new+'.md5':dict(size=32)}
        atomic_json(self.root/'baseline-copies.json',{self.old:pipeline.copy_identity(objects,self.old)})
        atomic_json(self.root/'known-copies.json',{key:pipeline.copy_identity(objects,key)
                                                  for key in [self.old,self.new]})
        with patch('pipeline.upload',return_value=set()), patch('pipeline.inventory',return_value=objects), \
             patch('pipeline.modules',side_effect=AssertionError('Acknowledged inputs must not be rescanned')):
            pipeline.process(self.cfg,'roms_hiig',self.root,'sync','recent',False)

    def test_checksum_success_does_not_acknowledge_an_unpublished_transfer(self):
        objects={**self.objects,self.new:dict(size=2),self.new+'.md5':dict(size=32)}
        atomic_json(self.root/'baseline-copies.json',{self.old:pipeline.copy_identity(objects,self.old)})
        atomic_json(self.root/'verified-copies.json',{self.new:{'identity':pipeline.copy_identity(objects,self.new)}})
        with patch('pipeline.upload',return_value=set()), patch('pipeline.inventory',return_value=objects), \
             patch('pipeline.modules',side_effect=RuntimeError('pending input reached update path')):
            with self.assertRaisesRegex(RuntimeError,'pending input reached update path'):
                pipeline.process(self.cfg,'roms_hiig',self.root,'sync','recent',False)

    def test_warm_routine_scans_only_incoming_run(self):
        model, bs, records = self.model_and_builder()
        objects = {**self.objects, self.new:dict(size=2), self.new+'.md5':dict(size=32)}
        atomic_json(self.work/'approved-runs.json', ['2026-11-17'])
        scanned, checked = [], []
        bs.scan.side_effect = lambda *a, **kw: scanned.append(list(model.list_runs().strftime('%Y-%m-%d')))
        bs.check.side_effect = lambda *a: checked.append(list(model.list_runs().strftime('%Y-%m-%d')))
        with patch('headers.load_reference', return_value={}):
            runs = headers.prepare(self.cfg, model, bs, self.work, objects, {self.new})
        self.assertEqual(scanned, [['2026-11-18']])
        self.assertEqual(checked, [['2026-11-17','2026-11-18']])
        self.assertEqual(runs, ['2026-11-17','2026-11-18'])
        self.assertNotIn('force', bs.scan.call_args.kwargs)

    def test_cold_routine_does_not_fill_historical_cache(self):
        model, bs, records = self.model_and_builder()
        with self.assertRaisesRegex(RuntimeError,'Normal sync will not scan the archive'):
            headers.prepare(self.cfg, model, bs, self.work, self.objects, set())
        bs.scan.assert_not_called()

    def test_full_explicitly_refreshes_all_headers_even_with_warm_cache(self):
        model, bs, records = self.model_and_builder()
        with patch('headers.remember_reference'):
            headers.prepare(self.cfg, model, bs, self.work, self.objects, set(), full=True)
        bs.scan.assert_called_once_with(self.work,2,force=True)
        bs.check.assert_called_once()

    def test_failed_forced_read_cannot_reuse_older_success(self):
        model, bs, records = self.model_and_builder()
        def scan(*a, **kw):
            with (self.work/'scan.jsonl').open('a') as out:
                out.write(json.dumps({'day':'2026-11-17','key':model.key('2026-11-17'),'error':'read failed'})+'\n')
        bs.scan.side_effect = scan
        with self.assertRaisesRegex(RuntimeError, 'older successes do not count'):
            headers.prepare(self.cfg,model,bs,self.work,self.objects,set(),full=True)
        bs.check.assert_not_called()

    def test_seed_reuses_headers_without_a_historical_source_read(self):
        model, bs, records = self.model_and_builder()
        seed = self.root / 'state/seeds/headers/roms_hiig'
        seed.mkdir(parents=True)
        content=(json.dumps(records['2026-11-17'])+'\n').encode()
        with gzip.open(seed/'scan.jsonl.gz','wb') as out:out.write(content)
        atomic_json(seed/'reference.json',{'coords':{},'mask_attrs':{}})
        atomic_json(seed/'approved-runs.json',['2026-11-17'])
        atomic_json(seed/'provenance.json',dict(bucket='bucket',prefix='pacioos',
            scan_sha256=hashlib.sha256(content).hexdigest(),
            copy_identities={self.old:pipeline.copy_identity(self.objects,self.old)}))
        headers.prepare(self.cfg,model,bs,self.work,self.objects,set())
        bs.scan.assert_not_called()
        bs.check.assert_not_called()
        self.assertEqual(read_json(self.work/'seed-adopted.json')['historical_files_read'],0)
        self.assertFalse((self.root/'last-success-full.json').exists())
        self.assertFalse((seed/'scan.jsonl.gz').exists())

    def test_incoming_sample_selection_never_includes_unselected_times(self):
        import xarray as xr
        times=pd.date_range('2026-11-01',periods=30,freq='h')
        ds=xr.Dataset(coords={'time':times, 'forecast_reference_time':('time',np.repeat(times.values[0],30))})
        allowed=np.array([0,1,5,12,29])
        picks=sample_indices(ds,allowed,'recent',4)
        self.assertTrue(set(picks).issubset(set(allowed)))


if __name__=='__main__':
    unittest.main()
