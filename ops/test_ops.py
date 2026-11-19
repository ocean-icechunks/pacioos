"""Offline tests. Never run bootstrap, connect to PacIOOS, or write remote storage."""
import contextlib
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
import jobs
import pipeline
import validation
import layout


def plan():
    times = pd.date_range('2026-11-01', '2026-11-25', freq='3h')
    origins = times.floor('D').where(times < pd.Timestamp('2026-11-18'), pd.Timestamp('2026-11-18'))
    return xr.Dataset(coords={'time': times, 'forecast_reference_time': ('time', origins),
                              'forecast_period': ('time', (times - origins) / pd.Timedelta('1h'))})


class ValidationTests(unittest.TestCase):
    def test_recent_is_anchored_to_wall_clock_and_includes_forecast(self):
        ds = plan()
        idx = validation.scope_indices(ds, 'recent', '2026-11-18T12:00:00Z', 3, 72)
        self.assertEqual(ds.time.values[idx[0]], np.datetime64('2026-11-15T12:00'))
        self.assertEqual(idx[-1], len(ds.time) - 1)
        picks = validation.sample_indices(ds, idx, 'recent', 8)
        self.assertLessEqual(len(picks), 8)
        self.assertTrue({int(idx[0]), int(idx[-1])}.issubset(picks))
        self.assertIn(int(np.flatnonzero(ds.forecast_reference_time.values == np.datetime64('2026-11-18'))[0]), picks)

    def test_stale_store_does_not_move_window_back(self):
        with self.assertRaisesRegex(ValueError, 'stale'):
            validation.scope_indices(plan(), 'recent', '2026-12-01T00:00:00Z', 3, 72)
        self.assertEqual(len(validation.scope_indices(plan(), 'full', '2026-12-01', 3, 72)), len(plan().time))

    def test_historical_defect_only_fails_full_coordinate_audit(self):
        expected = plan()
        actual = expected.copy(deep=True)
        values = actual.forecast_period.values.copy()
        values[0] = 999
        actual = actual.assign_coords(forecast_period=('time', values))
        recent = validation.scope_indices(expected, 'recent', '2026-11-18', 3, 72)
        validation.compare_coordinates(actual, expected, recent, ['forecast_period'])
        with self.assertRaises(AssertionError):
            validation.compare_coordinates(actual, expected, np.arange(len(expected.time)), ['forecast_period'])

    def test_empty_covered_recent_window_fails(self):
        ds = plan()
        ds = ds.assign_coords(forecast_reference_time=('time', np.full(len(ds.time), np.datetime64('NaT', 'ns'))))
        with self.assertRaises(ValueError):
            validation.scope_indices(ds, 'recent', '2026-11-18', 3, 72)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)

    def test_atomic_private_state_and_lock_release(self):
        dest = self.state / 'state.json'
        common.atomic_json(dest, {'value': 1})
        common.atomic_json(dest, {'value': 2})
        self.assertEqual(json.loads(dest.read_text()), {'value': 2})
        self.assertEqual(dest.stat().st_mode & 0o777, 0o600)
        with common.locked(self.state):
            with self.assertRaises(common.Busy):
                with common.locked(self.state):
                    pass
        with common.locked(self.state):
            pass

    def test_timeout_stops_worker_group(self):
        proc = Mock(pid=123)
        proc.wait.side_effect = [subprocess.TimeoutExpired('worker', 1), 0]
        manager = Mock()
        manager.__enter__ = Mock(return_value=proc)
        manager.__exit__ = Mock(return_value=False)
        with patch('common.subprocess.Popen', return_value=manager), patch('common.os.killpg') as kill:
            with self.assertRaises(subprocess.TimeoutExpired):
                common.run_bounded(['worker'], 1)
            kill.assert_called_once_with(123, signal.SIGTERM)

    def test_recover_commit_before_journal_snapshot_was_saved(self):
        common.atomic_json(self.state / 'pending-update.json', dict(
            before='old', token='job-unique', source_runs=['2026-11-17'], started='2026-11-18'))
        repo = Mock()
        repo.lookup_branch.return_value = 'new'
        repo.ancestry.return_value = [types.SimpleNamespace(id='new', message='job-unique: update')]
        with patch('pipeline.plan_for', return_value=('plan', [], '')), patch('pipeline.finish_validation') as verify:
            pipeline.recover({}, self.state, repo, 'public', 'builder', 'model', 'headers')
        self.assertEqual(verify.call_args.args[4], 'new')
        self.assertFalse((self.state / 'pending-update.json').exists())

    def test_failed_recovery_retains_pending_work(self):
        common.atomic_json(self.state / 'pending-update.json', dict(
            before='old', snapshot='new', source_runs=['2026-11-17'], started='2026-11-18'))
        with patch('pipeline.plan_for', return_value=('plan', [], '')), \
             patch('pipeline.finish_validation', side_effect=AssertionError('broken')):
            with self.assertRaises(AssertionError):
                pipeline.recover({}, self.state, Mock(), 'public', 'builder', 'model', 'headers')
        self.assertTrue((self.state / 'pending-update.json').exists())

    def test_uncommitted_transaction_can_be_replanned(self):
        common.atomic_json(self.state / 'pending-update.json', dict(before='old', token='unused'))
        repo = Mock()
        repo.lookup_branch.return_value = 'old'
        pipeline.recover({}, self.state, repo, 'public', 'builder', 'model', 'headers')
        self.assertFalse((self.state / 'pending-update.json').exists())


class CopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.key = 'pacioos/roms_hiig/netcdf/2026/file.nc'
        self.body = b'original bytes'
        self.objects = {self.key: {'size': len(self.body), 'etag': 'one', 'modified': 'date'},
                        self.key + '.md5': {'size': 40, 'etag': 'sidecar', 'modified': 'date'}}
        self.cfg = dict(bucket='bucket', prefix='pacioos')

    def download(self, url):
        return io.BytesIO((hashlib.md5(self.body).hexdigest() + '  file.nc').encode()
                          if url.endswith('.md5') else self.body)

    def test_verified_copy_is_not_downloaded_again(self):
        with patch('pipeline.get', side_effect=self.download) as get:
            pipeline.verify_copies(self.cfg, self.state, self.objects, [self.key])
            self.assertEqual(get.call_count, 2)
            pipeline.verify_copies(self.cfg, self.state, self.objects, [self.key])
            self.assertEqual(get.call_count, 2)

    def test_same_size_object_change_is_rejected(self):
        with patch('pipeline.get', side_effect=self.download):
            pipeline.verify_copies(self.cfg, self.state, self.objects, [self.key])
        self.objects[self.key]['etag'] = 'changed'
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            pipeline.verify_copies(self.cfg, self.state, self.objects, [self.key])

    def test_missing_sidecar_blocks_publication(self):
        del self.objects[self.key + '.md5']
        with self.assertRaisesRegex(RuntimeError, 'missing'):
            pipeline.verify_copies(self.cfg, self.state, self.objects, [self.key])

    def test_bad_download_never_enters_ledger(self):
        with patch('pipeline.get', side_effect=lambda url: io.BytesIO(b'0' * 32)):
            with self.assertRaises(RuntimeError):
                pipeline.verify_copies(self.cfg, self.state, self.objects, [self.key])
        self.assertFalse((self.state / 'verified-copies.json').exists())

    def test_baseline_is_saved_before_any_upload(self):
        self.cfg.update(datasets={'roms_hiig': {'update_store': True}})
        with patch('pipeline.inventory', return_value=self.objects), \
             patch('pipeline.upload', side_effect=RuntimeError('interrupted')):
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                pipeline.process(self.cfg, 'roms_hiig', self.state, 'sync', 'recent', False)
        self.assertIn(self.key, common.read_json(self.state / 'baseline-copies.json'))


class CronTests(unittest.TestCase):
    def test_render_is_unified_and_print_only(self):
        cfg = dict(config_file='/persistent/config file.toml', install_root='/persistent')
        block = jobs.cron_block(cfg)
        self.assertIn('/persistent/icechunker sync', block)
        self.assertIn('/persistent/icechunker verify --scope full', block)
        self.assertIn("'/persistent/config file.toml'", block)

    def test_schedule_injection_is_rejected(self):
        with self.assertRaises(ValueError):
            jobs.cron_block(dict(config_file='/config', sync_schedule='* * * * *\nrun-other-job'))


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.cfg = dict(key_file='/private/key', role_arn='role', rclone='/persistent/rclone',
                        upload_parallel=1, minimum_age_minutes=15, max_upload_batches=2,
                        bucket='bucket', prefix='pacioos', datasets={'roms_hiig': {'source_dir': '/source'}})
        self.helper = types.SimpleNamespace(read_key=Mock(return_value='long-lived-secret'),
            exchange=Mock(return_value=dict(AccessKeyId='temporary-secret', SecretAccessKey='secret',
                SessionToken='token', Expiration=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())))

    def proc(self, remaining, code=0):
        text = 'OK    roms_hiig/2026/new.nc  size=12  md5=abc\n'
        text += f'Finished date: 1 uploaded, 0 failed, {remaining} left for the next run, 0 changed\n'
        return contextlib.nullcontext(types.SimpleNamespace(stdout=io.StringIO(text), wait=lambda: code))

    def test_deferred_files_trigger_fresh_credentials_and_another_batch(self):
        output = io.StringIO()
        with patch.dict(sys.modules, {'source_coop_credentials': self.helper}), \
             patch('pipeline.subprocess.Popen', side_effect=[self.proc(1), self.proc(0)]), \
             contextlib.redirect_stdout(output):
            keys = pipeline.upload(self.cfg, 'roms_hiig', False)
        self.assertEqual(self.helper.exchange.call_count, 2)
        self.assertEqual(keys, {'pacioos/roms_hiig/netcdf/2026/new.nc'})
        self.assertNotIn('secret', output.getvalue())

    def test_backlog_at_batch_limit_is_not_success(self):
        with patch.dict(sys.modules, {'source_coop_credentials': self.helper}), \
             patch('pipeline.subprocess.Popen', side_effect=[self.proc(1), self.proc(1)]), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'deferred'):
                pipeline.upload(self.cfg, 'roms_hiig', False)

    def test_upload_failure_stops_without_retrying_changed_files(self):
        with patch.dict(sys.modules, {'source_coop_credentials': self.helper}), \
             patch('pipeline.subprocess.Popen', return_value=self.proc(0, 4)), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'exited 4'):
                pipeline.upload(self.cfg, 'roms_hiig', False)
        self.assertEqual(self.helper.exchange.call_count, 1)

    def test_reanalysis_success_keys_keep_version_folder(self):
        self.cfg['datasets']['roms_hiig_reanalysis'] = {'source_dir': '/source'}
        output = ('OK    roms_hiig_reanalysis/2020/hiig_his_zlevel_20201228.nc  size=12\n'
                  'Finished: 1 uploaded, 0 failed, 0 left for the next run, 0 changed\n')
        proc = contextlib.nullcontext(types.SimpleNamespace(stdout=io.StringIO(output), wait=lambda: 0))
        with patch.dict(sys.modules, {'source_coop_credentials': self.helper}), \
             patch('pipeline.subprocess.Popen', return_value=proc) as popen:
            keys = pipeline.upload(self.cfg, 'roms_hiig_reanalysis', False)
        self.assertEqual(keys, {'pacioos/roms_hiig_reanalysis/netcdf/v2.0/2020/hiig_his_zlevel_20201228.nc'})
        # Empty override leaves the uploader's existing v2.0 product default intact.
        self.assertEqual(popen.call_args.kwargs['env']['VERSION'], '')


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.home(), prefix='.icechunker-config-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, ICECHUNKER_ROOT=str(self.root))
        self.env.start()
        self.addCleanup(self.env.stop)

    def config(self, extra=''):
        with tempfile.NamedTemporaryFile('w', suffix='.toml', dir=self.root) as file:
            file.write('state_dir = "state"\nrclone = "tools/rclone"\n' + extra +
                       '\n[datasets.roms_hiig]\nsource_dir = "/source"\n')
            file.flush()
            return common.load_config(file.name)

    def test_alternate_persistent_paths(self):
        cfg = self.config('bucket = "another-bucket"\nprefix = "test/pacioos"\n')
        self.assertEqual(cfg['datasets']['roms_hiig']['store_prefix'], 'test/pacioos/roms_hiig/icechunk')
        self.assertEqual(cfg['state_dir'], str(self.root / 'state'))
        self.assertEqual(cfg['key_file'], str(self.root / 'source-coop.key'))

    def test_invalid_sample_budget_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'at least 4'):
            self.config('verify_samples = 1\n')

    def test_reanalysis_defaults_to_copies_and_readme_only(self):
        cfg = self.config('[datasets.roms_hiig_reanalysis]\nsource_dir = "/source"\n')
        self.assertFalse(cfg['datasets']['roms_hiig_reanalysis']['update_store'])
        self.assertEqual(cfg['datasets']['roms_hiig_reanalysis']['store_prefix'],
                         'pacioos/roms_hiig_reanalysis/icechunk')
        with self.assertRaisesRegex(ValueError, 'does not have a store updater'):
            self.config('[datasets.roms_hiig_reanalysis]\nsource_dir = "/source"\nupdate_store = true\n')

    def test_external_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'key_file must stay inside'):
            self.config('key_file = "/outside/key"\n')

    def test_optional_notification_settings_are_not_validated_during_config_load(self):
        cfg = self.config('[notifications]\nsmtp_password_file = "config/smtp-password"\n')
        self.assertEqual(cfg['notifications']['smtp_password_file'], 'config/smtp-password')
        cfg = self.config('[notifications]\nsmtp_password_file = "/outside/password"\n')
        self.assertEqual(cfg['notifications']['smtp_password_file'], '/outside/password')
        cfg = self.config('[notifications]\nsmtp_password_file = 42\n')
        self.assertEqual(cfg['notifications']['smtp_password_file'], 42)
        cfg = self.config('notifications = "invalid optional setting"\n')
        self.assertEqual(cfg['notifications'], 'invalid optional setting')

    def test_direct_python_job_environment_and_working_directory_stay_inside_root(self):
        cfg = self.config()
        (self.root / '.runtime/tmp').mkdir(parents=True)
        original = Path.cwd()
        try:
            with patch.dict(os.environ), patch.object(tempfile, 'tempdir', tempfile.tempdir):
                common.activate_environment(cfg)
                self.assertEqual(Path.cwd(), self.root)
                self.assertEqual(tempfile.gettempdir(), str(self.root / '.runtime/tmp'))
                self.assertEqual(os.environ['PIP_CACHE_DIR'], str(self.root / '.runtime/cache/pip'))
        finally:
            os.chdir(original)

    def test_external_config_is_rejected_before_open(self):
        with self.assertRaisesRegex(ValueError, 'Config file must stay inside'):
            common.load_config('/outside/config.toml')

    def test_symlink_escape_is_rejected(self):
        (self.root / 'escape').symlink_to(self.root.parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'key_file must stay inside'):
            self.config('key_file = "escape/private.key"\n')


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.home(), prefix='.icechunker-layout-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_all_managed_environment_paths_are_beneath_root(self):
        env = layout.environment(self.root)
        for key, value in env.items():
            if value.startswith('/') and value != '/dev/null':
                self.assertTrue(Path(value).is_relative_to(self.root), key)
        self.assertNotIn('HOME', env)
        self.assertEqual(env['TMPDIR'], str(self.root / '.runtime/tmp'))
        self.assertEqual(env['SOURCE_COOP_CREDS_CACHE'], str(self.root / '.runtime/cache/source-coop/credentials/_default.json'))

    def test_generated_environment_keeps_temp_and_bytecode_inside_root(self):
        env = os.environ.copy()
        env.update(layout.environment(self.root))
        (self.root / '.runtime/tmp').mkdir(parents=True)
        result = subprocess.check_output([sys.executable, '-c',
            'import json,os,sys,tempfile; print(json.dumps([tempfile.gettempdir(),sys.pycache_prefix,os.environ["HOME"]]))'],
            env=env, text=True)
        temporary, pycache, home = json.loads(result)
        self.assertEqual(temporary, str(self.root / '.runtime/tmp'))
        self.assertEqual(pycache, str(self.root / '.runtime/cache/pycache'))
        self.assertEqual(home, os.environ['HOME'])

    def test_auxiliary_symlink_escape_is_rejected(self):
        (self.root / '.runtime').mkdir()
        (self.root / '.runtime/cache').symlink_to(self.root.parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'must stay inside'):
            layout.environment(self.root)

    def test_bootstrap_layout_rejects_external_state_before_creating_it(self):
        external = self.root.parent / 'icechunker-must-not-create-state'
        with patch.object(sys, 'argv', ['layout.py', 'bootstrap', str(self.root), str(external), '', '']):
            with self.assertRaisesRegex(ValueError, 'State directory must stay inside'):
                layout.main()
        self.assertFalse(external.exists())

    def test_python_must_also_be_inside_root(self):
        with patch.object(sys, 'argv', ['layout.py', 'bootstrap', str(self.root), '', '', '/usr/bin/python3']):
            with self.assertRaisesRegex(ValueError, 'Python interpreter must stay inside'):
                layout.main()

    def test_setup_package_must_also_be_inside_root(self):
        with patch.object(sys, 'argv', ['layout.py', 'bootstrap', str(self.root), '', '', '', '/outside/setup']):
            with self.assertRaisesRegex(ValueError, 'Setup source directory must stay inside'):
                layout.main()

    def test_shell_environment_quotes_paths_and_does_not_reassign_home(self):
        env = layout.shell_environment(self.root / "with space's")
        self.assertIn('export ICECHUNKER_ROOT=', env)
        self.assertNotIn('export HOME=', env)
        self.assertIn('unset SSLKEYLOGFILE', env)



if __name__ == '__main__':
    unittest.main()
