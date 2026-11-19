"""Offline README publication, real file-header and retry regressions."""
import contextlib
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import ThreadingHTTPServer
import io
from pathlib import Path
import sys
import tempfile
from threading import Thread
import types
import unittest
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError
import netCDF4
import numpy as np

from common import atomic_json, read_json
import dataset_readme as docs
import pipeline

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'stores'))


class ReadmeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.cfg = dict(bucket='bucket', prefix='pacioos', datasets={
            'wrf_hi': dict(update_store=False),
            'roms_hiig': dict(update_store=True, store_prefix='pacioos/roms_hiig/icechunk'),
            'roms_hiig_reanalysis': dict(update_store=False,
                store_prefix='pacioos/roms_hiig_reanalysis/icechunk')})
        self.old = 'pacioos/wrf_hi/netcdf/2026/wrf_20261117.nc'
        self.new = 'pacioos/wrf_hi/netcdf/2026/wrf_20261118.nc'
        self.completed = {self.old: dict(data={'etag': 'old'}, sidecar={'etag': 'old-md5'}),
                          self.new: dict(data={'etag': 'new'}, sidecar={'etag': 'new-md5'})}

    def cached(self, key=None):
        key = key or self.new
        return dict(key=key, identity=self.completed[key], attributes={'title': 'test'})

    def client(self, text='', missing=False):
        client = Mock()
        client.create_multipart_upload.return_value = {'UploadId': 'upload'}
        client.upload_part.return_value = {'ETag': 'part'}
        if missing:
            client.get_object.side_effect = ClientError(
                {'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
        else:
            client.get_object.return_value = dict(Body=io.BytesIO(text.encode()), ETag='"etag"')
        return client

    def test_real_headers_in_all_supported_formats_without_array_reads(self):
        for fmt in ('NETCDF3_CLASSIC', 'NETCDF3_64BIT_OFFSET', 'NETCDF4'):
            with self.subTest(fmt=fmt):
                filename = self.state / (fmt + '.nc')
                with netCDF4.Dataset(filename, 'w', format=fmt) as ds:
                    ds.title = 'Hawaiʻi | waves\nnext line'
                    ds.numbers = np.array([1, 2], dtype='i4')
                    ds.empty = ''
                    ds.createDimension('x', 1_000_000)
                    ds.createVariable('science', 'f4', ('x',))
                    expected = docs.plain({k: ds.getncattr(k) for k in ds.ncattrs()})
                # The reader stops before variable data; reject large data reads.
                import fsspec
                original = fsspec.open
                count = [0]
                def tracked(*args, **kwargs):
                    file = original(*args, **kwargs).open()
                    read = file.read
                    def small(size=-1):
                        if size < 0 or size > 65536:
                            raise AssertionError(f'Unexpected array-sized read: {size}')
                        count[0] += size
                        return read(size)
                    file.read = small
                    return types.SimpleNamespace(open=lambda: file)
                with patch('fsspec.open', side_effect=tracked):
                    actual = docs.netcdf_attributes(str(filename))
                self.assertEqual(actual, expected)
                self.assertLess(count[0], 65536)

    def test_public_header_reads_over_http_ranges(self):
        from test_local_store import RangeHandler
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(RangeHandler, directory=str(self.state)))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for fmt in ('NETCDF3_CLASSIC', 'NETCDF4'):
                filename = self.state / (fmt + '.nc')
                with netCDF4.Dataset(filename, 'w', format=fmt) as ds:
                    ds.title = 'Header over HTTP'
                    ds.createDimension('x', 1_000_000)
                    ds.createVariable('science', 'f4', ('x',))
                url = f'http://127.0.0.1:{server.server_port}/{filename.name}'
                self.assertEqual(docs.netcdf_attributes(url), {'title': 'Header over HTTP'})
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_empty_global_headers(self):
        for fmt in ('NETCDF3_CLASSIC', 'NETCDF4'):
            filename = self.state / (fmt + '.nc')
            with netCDF4.Dataset(filename, 'w', format=fmt):
                pass
            self.assertEqual(docs.netcdf_attributes(str(filename)), {})

    def test_table_is_sorted_escaped_and_handles_nonfinite_arrays(self):
        attributes = docs.plain({'z': np.array([1, np.nan, np.inf]),
                                 'a|<': b'line1\n</code>| **raw**', 'empty': ''})
        rendered = docs.table(attributes)
        self.assertLess(rendered.index('a&#124;&lt;'), rendered.index('<code>z</code>'))
        self.assertIn('line1<br>&lt;/code&gt;&#124;', rendered)
        self.assertIn('&#42;&#42;raw&#42;&#42;', rendered)
        self.assertIn('&quot;nan&quot;', rendered)
        self.assertEqual(docs.table({}), 'No global attributes.\n')

    def test_section_preserves_prose_and_is_idempotent(self):
        block = docs.section(self.cfg, self.cached(), None)
        original = '# Existing\n\nCarefully written prose.\n'
        candidate = docs.replace_section(original, block, 'wrf_hi')
        self.assertTrue(candidate.startswith(original))
        with_tail = candidate + '\n## Handwritten footer\nKeep this.\n'
        replaced = docs.replace_section(with_tail, block.replace('test', 'new'), 'wrf_hi')
        self.assertTrue(replaced.endswith('\n## Handwritten footer\nKeep this.\n'))
        self.assertEqual(docs.replace_section(candidate, block, 'wrf_hi'), candidate)
        self.assertIn('no published Icechunk store', candidate)
        self.assertIn('File: [wrf_20261118.nc]', candidate)
        self.assertIn('snapshot <code>abc</code>', docs.section(self.cfg, self.cached(),
            dict(url='https://example.test/store', snapshot='abc', attributes={})))

    def test_bad_markers_are_rejected(self):
        for original in (docs.START, docs.END, docs.END + docs.START,
                         docs.START + docs.START + docs.END):
            with self.assertRaises(ValueError):
                docs.replace_section(original, 'block', 'wrf_hi')

    def test_publish_skips_unchanged_and_uses_conditional_writes(self):
        block = docs.section(self.cfg, self.cached(), None)
        candidate = docs.replace_section('# Original\n', block, 'wrf_hi')
        client = self.client(candidate)
        with patch('dataset_readme.s3_client', return_value=client):
            docs.publish(self.cfg, 'wrf_hi', block)
        client.create_multipart_upload.assert_not_called()
        client.close.assert_called_once()
        client = self.client('# Original\n')
        with patch('dataset_readme.s3_client', return_value=client):
            docs.publish(self.cfg, 'wrf_hi', block)
        kwargs = client.complete_multipart_upload.call_args.kwargs
        self.assertEqual(kwargs['IfMatch'], '"etag"')
        self.assertEqual(kwargs['Key'], 'pacioos/wrf_hi/README.md')
        self.assertEqual(client.upload_part.call_args.kwargs['Body'].decode(), candidate)
        self.assertEqual(client.create_multipart_upload.call_args.kwargs['ContentType'],
                         'text/markdown; charset=utf-8')

    def test_missing_readme_is_created_but_access_errors_propagate(self):
        client = self.client(missing=True)
        with patch('dataset_readme.s3_client', return_value=client):
            docs.publish(self.cfg, 'wrf_hi', 'block')
        self.assertEqual(client.complete_multipart_upload.call_args.kwargs['IfNoneMatch'], '*')
        self.assertTrue(client.upload_part.call_args.kwargs['Body'].startswith(b'# PacIOOS wrf_hi'))
        for code in ('AccessDenied', 'NoSuchBucket', 'InternalError'):
            client = self.client()
            client.get_object.side_effect = ClientError({'Error': {'Code': code}}, 'GetObject')
            with patch('dataset_readme.s3_client', return_value=client):
                with self.assertRaises(ClientError):
                    docs.publish(self.cfg, 'wrf_hi', 'block')
            client.create_multipart_upload.assert_not_called()

    def test_concurrent_edit_failure_retains_work_and_retry_reads_new_prose(self):
        atomic_json(self.state / 'readme-netcdf.json', self.cached())
        client = self.client('# Before concurrent edit\n')
        client.complete_multipart_upload.side_effect = ClientError({'Error': {'Code': 'PreconditionFailed'}}, 'CompleteMultipartUpload')
        with patch('dataset_readme.s3_client', return_value=client):
            with self.assertRaises(ClientError):
                docs.reconcile(self.cfg, 'wrf_hi', self.state, self.completed)
        self.assertTrue((self.state / 'pending-readme.json').exists())
        client.abort_multipart_upload.assert_called_once_with(Bucket='bucket',
            Key='pacioos/wrf_hi/README.md', UploadId='upload')
        client = self.client('# Concurrent edit preserved\n')
        with patch('dataset_readme.s3_client', return_value=client):
            docs.reconcile(self.cfg, 'wrf_hi', self.state, self.completed)
        self.assertTrue(client.upload_part.call_args.kwargs['Body'].startswith(b'# Concurrent edit preserved\n'))
        self.assertFalse((self.state / 'pending-readme.json').exists())

    def test_credentials_are_fresh_explicit_and_expiry_checked(self):
        helper = types.SimpleNamespace(read_key=Mock(return_value='private'), exchange=Mock())
        cfg = dict(self.cfg, key_file='/private/key', role_arn='role')
        temporary = dict(AccessKeyId='access', SecretAccessKey='secret', SessionToken='token',
                         Expiration=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
        helper.exchange.return_value = temporary
        with patch.dict(sys.modules, {'source_coop_credentials': helper}), patch('boto3.client') as client:
            docs.s3_client(cfg)
        self.assertEqual(client.call_args.kwargs['region_name'], 'us-east-1')
        self.assertEqual(client.call_args.kwargs['aws_session_token'], 'token')
        temporary['Expiration'] = datetime.now(timezone.utc).isoformat()
        with patch.dict(sys.modules, {'source_coop_credentials': helper}), patch('boto3.client') as client:
            with self.assertRaisesRegex(RuntimeError, 'credential lifetime'):
                docs.s3_client(cfg)
        client.assert_not_called()
        self.assertEqual(helper.exchange.call_count, 2)

    def test_no_transfer_without_cache_reads_no_headers_or_store(self):
        with patch('dataset_readme.netcdf_attributes') as read, \
             patch('dataset_readme.store_attributes') as store, patch('dataset_readme.publish') as publish:
            docs.reconcile(self.cfg, 'wrf_hi', self.state, self.completed)
        read.assert_not_called()
        store.assert_not_called()
        publish.assert_not_called()

    def test_backfill_does_not_replace_newer_cached_file(self):
        atomic_json(self.state / 'readme-netcdf.json', self.cached())
        with patch('dataset_readme.netcdf_attributes') as read:
            docs.prepare_file(self.cfg, 'wrf_hi', self.state, self.completed, {self.old})
        read.assert_not_called()
        self.assertEqual(read_json(self.state / 'readme-netcdf.json')['key'], self.new)

    def test_first_transfer_selects_latest_file_and_immutable_cache_is_checked(self):
        with patch('dataset_readme.netcdf_attributes', return_value={'title': 'new'}) as read:
            docs.prepare_file(self.cfg, 'wrf_hi', self.state, self.completed, {self.old})
        self.assertTrue(read.call_args.args[0].endswith('wrf_20261118.nc'))
        changed = {**self.completed, self.new: {'data': {'etag': 'changed'}}}
        with self.assertRaisesRegex(RuntimeError, 'identity changed'):
            docs.prepare_file(self.cfg, 'wrf_hi', self.state, changed, ())

    def test_dry_run_has_no_state_or_remote_writes(self):
        client = self.client(missing=True)
        with patch('dataset_readme.netcdf_attributes', return_value={}), \
             patch('dataset_readme.s3_client', return_value=client):
            docs.reconcile(self.cfg, 'wrf_hi', self.state, self.completed, {self.new}, dry_run=True)
        client.create_multipart_upload.assert_not_called()
        self.assertEqual(list(self.state.iterdir()), [])

    def test_readme_failure_is_retried_after_data_acknowledgment_without_transfer_work(self):
        objects = {}
        for key, identity in self.completed.items():
            objects[key] = identity['data']
            objects[key + '.md5'] = identity['sidecar']
        atomic_json(self.state / 'baseline-copies.json', {})
        with patch('pipeline.upload', return_value={self.new}), \
             patch('pipeline.inventory', return_value=objects), \
             patch('pipeline.verify_copies') as verify, \
             patch('dataset_readme.netcdf_attributes', return_value={'title': 'new'}), \
             patch('dataset_readme.publish', side_effect=RuntimeError('readme write failed')):
            with self.assertRaisesRegex(RuntimeError, 'readme write failed'):
                pipeline.process(self.cfg, 'wrf_hi', self.state, 'sync', 'recent', False)
        verify.assert_called_once()
        self.assertEqual(read_json(self.state / 'known-copies.json'), self.completed)
        self.assertTrue((self.state / 'pending-readme.json').exists())
        with patch('pipeline.upload', return_value=set()), patch('pipeline.inventory', return_value=objects), \
             patch('pipeline.verify_copies') as verify, patch('pipeline.modules') as model, \
             patch('dataset_readme.netcdf_attributes') as read, patch('dataset_readme.publish') as publish:
            pipeline.process(self.cfg, 'wrf_hi', self.state, 'sync', 'recent', False)
        verify.assert_not_called()
        model.assert_not_called()
        read.assert_not_called()
        publish.assert_called_once()
        self.assertFalse((self.state / 'pending-readme.json').exists())

    def test_interruption_after_acknowledgment_preserves_snapshot_and_reloads_prose(self):
        with patch('dataset_readme.netcdf_attributes', return_value={}), \
             patch('dataset_readme.store_attributes', side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError):
                pipeline.complete_sync(self.cfg, 'roms_hiig', self.state, self.completed, {self.new}, 'validated')
        self.assertEqual(read_json(self.state / 'pending-readme.json')['snapshot'], 'validated')
        client = self.client('# Edited while job was down\n')
        with patch('dataset_readme.store_attributes', return_value=None) as store, \
             patch('dataset_readme.s3_client', return_value=client):
            docs.reconcile(self.cfg, 'roms_hiig', self.state, self.completed)
        self.assertEqual(store.call_args.args[2], 'validated')
        self.assertTrue(client.upload_part.call_args.kwargs['Body'].startswith(b'# Edited while job was down\n'))

    def test_committed_store_is_not_committed_again_after_readme_failure(self):
        import best_series_update
        key = self.new.replace('/wrf_hi/', '/roms_hiig/')
        objects = {key: {'etag': 'data'}, key + '.md5': {'etag': 'sidecar'}}
        atomic_json(self.state / 'baseline-copies.json', {})
        self.cfg.update(verify_lookback_days=3, max_run_age_hours=72)
        planned = types.SimpleNamespace(time=types.SimpleNamespace(
            values=np.array(['2026-11-18'], dtype='datetime64[ns]')))
        repo = Mock()
        repo.reopen.return_value = repo
        repo.lookup_branch.return_value = 'before'
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch('pipeline.upload', return_value={key}))
            stack.enter_context(patch('pipeline.inventory', return_value=objects))
            stack.enter_context(patch('pipeline.modules', return_value=(Mock(), Mock())))
            stack.enter_context(patch('headers.prepare', return_value=['2026-11-18']))
            stack.enter_context(patch('pipeline.plan_for', return_value=(planned, ['2026-11-18'], None)))
            stack.enter_context(patch('icechunk_utils.open_source_icechunk_repo',
                                       return_value=(repo, None, None, None)))
            stack.enter_context(patch.object(best_series_update, 'read_state'))
            stack.enter_context(patch.object(best_series_update, 'plan_changes', return_value=dict(
                appended=1, repointed=0, changed=np.array([0]))))
            commit = stack.enter_context(patch.object(best_series_update, 'apply_update', return_value='after'))
            stack.enter_context(patch('validation.scope_indices'))
            stack.enter_context(patch('pipeline.manifest_keys', return_value=set()))
            verify = stack.enter_context(patch('pipeline.verify_copies'))
            stack.enter_context(patch('pipeline.finish_validation'))
            stack.enter_context(patch('dataset_readme.netcdf_attributes', return_value={'title': 'file'}))
            stack.enter_context(patch('dataset_readme.store_attributes', return_value=dict(
                url='https://example.test/store', snapshot='after', attributes={'title': 'store'})))
            publish = stack.enter_context(patch('dataset_readme.publish', side_effect=RuntimeError('README failed')))
            with self.assertRaisesRegex(RuntimeError, 'README failed'):
                pipeline.process(self.cfg, 'roms_hiig', self.state, 'sync', 'recent', False)
            self.assertFalse((self.state / 'pending-update.json').exists())
            self.assertTrue((self.state / 'pending-readme.json').exists())
            publish.side_effect = None
            with patch('pipeline.upload', return_value=set()):
                pipeline.process(self.cfg, 'roms_hiig', self.state, 'sync', 'recent', False)
        commit.assert_called_once()
        verify.assert_called_once()
        self.assertEqual(publish.call_count, 2)
        self.assertFalse((self.state / 'pending-readme.json').exists())

    def test_idle_cache_reconciles_changed_store_without_reading_netcdf(self):
        atomic_json(self.state / 'readme-netcdf.json', self.cached())
        with patch('dataset_readme.netcdf_attributes') as read, \
             patch('dataset_readme.store_attributes', return_value=dict(
                 url='https://example.test/store', snapshot='new', attributes={'title': 'changed'})), \
             patch('dataset_readme.publish') as publish:
            docs.reconcile(self.cfg, 'roms_hiig', self.state, self.completed)
        read.assert_not_called()
        self.assertIn('changed', publish.call_args.args[2])

    def test_verify_does_not_reconcile_readmes(self):
        for name in ('wrf_hi', 'roms_hiig_reanalysis'):
            with patch('dataset_readme.reconcile') as reconcile, patch('pipeline.upload') as upload:
                pipeline.process(self.cfg, name, self.state, 'verify', 'full', False)
            reconcile.assert_not_called()
            upload.assert_not_called()

    def test_store_attributes_are_read_from_real_snapshot_and_reanalysis_tag(self):
        import icechunk
        import zarr
        storage = icechunk.local_filesystem_storage(str(self.state / 'icechunk'))
        repo = icechunk.Repository.create(storage)
        writer = repo.writable_session('main')
        group = zarr.open_group(writer.store, mode='w')
        group.attrs.update(title='published', array=[1, 2])
        snapshot = writer.commit('initial')
        repo.create_tag('v2.0', snapshot_id=snapshot)
        writer = repo.writable_session('main')
        zarr.open_group(writer.store, mode='a').attrs['title'] = 'new main'
        newest = writer.commit('new main')
        with patch('icechunk.http_storage', return_value=storage):
            reanalysis = docs.store_attributes(self.cfg, 'roms_hiig_reanalysis')
            forecast = docs.store_attributes(self.cfg, 'roms_hiig')
            pinned = docs.store_attributes(self.cfg, 'roms_hiig', snapshot)
        self.assertEqual(reanalysis['snapshot'], snapshot)
        self.assertEqual(reanalysis['attributes'], {'title': 'published', 'array': [1, 2]})
        self.assertEqual(forecast['snapshot'], newest)
        self.assertEqual(pinned['attributes']['title'], 'published')
        self.assertIsNone(docs.store_attributes(self.cfg, 'wrf_hi'))


if __name__ == '__main__':
    unittest.main()
