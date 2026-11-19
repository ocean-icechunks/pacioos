"""Parent-only CLI exception alerts cover setup and orchestration without replacing errors."""
import contextlib
import fcntl
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import cli
import common
import jobs


class ParentBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=Path.home(), prefix='.icechunker-boundary-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / '.runtime/tmp').mkdir(parents=True)
        environment = patch.dict(os.environ, ICECHUNKER_ROOT=str(self.root))
        environment.start()
        self.addCleanup(environment.stop)
        self.addCleanup(setattr, tempfile, 'tempdir', tempfile.tempdir)
        self.cfg = dict(install_root=str(self.root), config_file=str(self.root / 'config.toml'),
                        state_dir=str(self.root / 'state'), bucket='bucket', prefix='pacioos',
                        notifications=dict(to_addresses=['ops@example.org'],
                                           from_address='icechunker@example.org',
                                           smtp_host='smtp.example.org'),
                        max_job_seconds=20, datasets={'roms_hiig': dict(store_prefix='pacioos/roms_hiig/icechunk')})

    def test_setup_exceptions_are_alerted_once_without_raw_text_and_reraised(self):
        for error_type in (ValueError, OSError, KeyError, TypeError, AttributeError):
            error = error_type('credential-secret')
            with self.subTest(error=error_type.__name__), \
                    patch('jobs.load_config', side_effect=error), \
                    patch('common.load_config', return_value=self.cfg), \
                    patch('notifications.send_message') as send:
                with self.assertRaises(error_type) as raised:
                    cli.main(['sync', '--notify'])
            self.assertIs(raised.exception, error)
            send.assert_called_once()
            body = send.call_args.args[2]
            self.assertIn('parent-job: failed (' + error_type.__name__ + ')', body)
            self.assertIn('work may be incomplete', body)
            self.assertIn('Log directory: ' + str(self.root / 'logs'), body)
            self.assertNotIn('Logs (if created):', body)
            self.assertNotIn('credential-secret', body)

    def test_path_validation_and_lock_file_permission_failures_are_alerted(self):
        for target, error in [('layout.installation_root', ValueError('credential-secret')),
                              ('pathlib.Path.open', PermissionError('credential-secret'))]:
            with self.subTest(target=target), patch(target, side_effect=error), \
                    patch('common.load_config', return_value=self.cfg), \
                    patch('notifications.send_message') as send:
                with self.assertRaises(type(error)) as raised:
                    cli.main(['verify', '--scope', 'full', '--notify'])
            self.assertIs(raised.exception, error)
            send.assert_called_once()
            self.assertIn('verify (scope: full)', send.call_args.args[1])
            self.assertNotIn('credential-secret', send.call_args.args[2])

    def test_jobs_import_failure_is_inside_parent_boundary(self):
        original_import = __import__
        error = ImportError('credential-secret')
        def importing(name, *args, **kwargs):
            if name == 'jobs':
                raise error
            return original_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=importing), \
                patch('common.load_config', return_value=self.cfg), \
                patch('notifications.send_message') as send:
            with self.assertRaises(ImportError) as raised:
                cli.main(['sync', '--notify'])
        self.assertIs(raised.exception, error)
        send.assert_called_once()
        self.assertIn('ImportError', send.call_args.args[2])
        self.assertNotIn('credential-secret', send.call_args.args[2])

    def test_failed_timeout_bookkeeping_alerts_without_changing_original_error_or_pending_state(self):
        error = OSError('credential-secret')
        state = common.dataset_state(self.cfg, 'roms_hiig')
        pending = state / 'pending-update.json'
        common.atomic_json(pending, {'token': 'preserve'})
        before = pending.read_bytes()
        with patch('jobs.load_config', return_value=self.cfg), patch('jobs.activate_environment'), \
                patch('common.load_config', return_value=self.cfg), \
                patch('jobs.run_bounded', side_effect=subprocess.TimeoutExpired('worker', 20)), \
                patch('jobs.atomic_json', side_effect=error), patch('notifications.send_message') as send:
            with self.assertRaises(OSError) as raised:
                cli.main(['sync', '--notify'])
        self.assertIs(raised.exception, error)
        self.assertEqual(pending.read_bytes(), before)
        send.assert_called_once()
        self.assertIn('parent-job: failed (OSError)', send.call_args.args[2])
        self.assertNotIn('credential-secret', send.call_args.args[2])

    def test_ordinary_aggregated_worker_failure_is_not_notified_twice(self):
        with patch('jobs.load_config', return_value=self.cfg), patch('jobs.activate_environment'), \
                patch('jobs.run_bounded', return_value=1), patch('notifications.send_message') as send, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['sync', '--notify']), 1)
        send.assert_called_once()
        self.assertIn('roms_hiig: failed (exit 1)', send.call_args.args[2])
        self.assertNotIn('parent-job', send.call_args.args[2])

    def test_manual_dry_run_worker_and_unrelated_commands_never_send_parent_alerts(self):
        error = ValueError('invalid root')
        commands = [['sync'], ['verify'], ['sync', '--notify', '--dry-run'],
                    ['sync', '--notify', '--worker', 'roms_hiig'],
                    ['verify', '--notify', '--worker', 'roms_hiig'],
                    ['check'], ['status'], ['cron'], ['clean']]
        for command in commands:
            with self.subTest(command=command), patch('layout.installation_root', side_effect=error), \
                    patch('notifications.send_message') as send:
                with self.assertRaises(ValueError) as raised:
                    cli.main(command)
            self.assertIs(raised.exception, error)
            send.assert_not_called()

    def test_expected_installation_lock_contention_is_silent_and_still_nonzero(self):
        (self.root / 'state').mkdir()
        with (self.root / 'state/installation.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch('notifications.send_message') as send:
                with self.assertRaises(cli.InstallationBusy):
                    cli.main(['sync', '--notify'])
        send.assert_not_called()

    def test_reporting_failure_does_not_replace_original_parent_exception(self):
        error = TypeError('credential-secret')
        with patch('jobs.load_config', side_effect=error), \
                patch('common.load_config', return_value=self.cfg), \
                patch('notifications.notify_failures', side_effect=RuntimeError('smtp-secret')), \
                contextlib.redirect_stderr(io.StringIO()) as output:
            with self.assertRaises(TypeError) as raised:
                cli.main(['sync', '--notify'])
        self.assertIs(raised.exception, error)
        self.assertIn('parent failure notification unavailable', output.getvalue())
        self.assertNotIn('credential-secret', output.getvalue())
        self.assertNotIn('smtp-secret', output.getvalue())


if __name__ == '__main__':
    unittest.main()
