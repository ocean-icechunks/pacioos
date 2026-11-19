"""Offline tests for parent-owned scheduled failure alerts; SMTP is always mocked."""
import argparse
import contextlib
import io
import os
from pathlib import Path
import smtplib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import cli
import common
import job_reports
import jobs
import notifications
import package


SMTP_SETTINGS = {
    'PACIOOS_ALERT_EMAIL_TO': 'ops@example.org, team@example.org',
    'PACIOOS_ALERT_EMAIL_FROM': 'icechunker@example.org',
    'PACIOOS_SMTP_HOST': 'smtp.example.org',
    'PACIOOS_SMTP_USERNAME': 'mailer',
    'PACIOOS_SMTP_PASSWORD': 'smtp-secret',
}


class SMTPTests(unittest.TestCase):
    def setUp(self):
        settings = patch.dict(os.environ, SMTP_SETTINGS, clear=True)
        settings.start()
        self.addCleanup(settings.stop)

    def test_starttls_summary_and_envelope_exclude_credentials(self):
        with patch('notifications.smtplib.SMTP') as client:
            client.return_value.__enter__.return_value.send_message.return_value = {}
            notifications.notify_failures('verify', 'full', [
                ('roms_hiig', 'failed (exit 1)'), ('ww3_hawaii', 'timed out')], Path('/root/logs'),
                details={name: dict(log_path=f'/root/logs/{name}-verify-current.log')
                         for name in ('roms_hiig', 'ww3_hawaii')})
        client.assert_called_once_with('smtp.example.org', 587, timeout=30)
        smtp = client.return_value.__enter__.return_value
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with('mailer', 'smtp-secret')
        smtp.send_message.assert_called_once()
        message = smtp.send_message.call_args.args[0]
        self.assertIn('verify (scope: full)', message['Subject'])
        self.assertEqual(message['To'], 'ops@example.org, team@example.org')
        self.assertEqual(smtp.send_message.call_args.kwargs,
                         dict(from_addr='icechunker@example.org',
                              to_addrs=['ops@example.org', 'team@example.org']))
        for value in ('roms_hiig: failed', 'ww3_hawaii: timed out',
                      '/root/logs/roms_hiig-verify-current.log', '/root/logs/ww3_hawaii-verify-current.log'):
            self.assertIn(value, message.get_content())
        self.assertNotIn('smtp-secret', message.as_string())
        self.assertNotIn('Traceback', message.get_content())

    def test_ssl_and_custom_port(self):
        with patch.dict(os.environ, PACIOOS_SMTP_SECURITY='ssl', PACIOOS_SMTP_PORT='2465'), \
                patch('notifications.smtplib.SMTP_SSL') as client:
            client.return_value.__enter__.return_value.send_message.return_value = {}
            notifications.send_message('failure', 'summary')
        self.assertEqual(client.call_args.args, ('smtp.example.org', 2465))
        self.assertIn('context', client.call_args.kwargs)
        client.return_value.__enter__.return_value.starttls.assert_not_called()

    def test_invalid_configuration_never_connects_or_logs_values(self):
        for override in ({'PACIOOS_ALERT_EMAIL_TO': ''},
                         {'PACIOOS_ALERT_EMAIL_TO': 'ops@example.org\nBcc: secret@example.org'},
                         {'PACIOOS_ALERT_EMAIL_FROM': 'sender@example.org\r\nsecret'},
                         {'PACIOOS_SMTP_HOST': ''},
                         {'PACIOOS_SMTP_SECURITY': 'plain'},
                         {'PACIOOS_SMTP_PORT': 'smtp-secret'},
                         {'PACIOOS_SMTP_PASSWORD': ''}):
            with self.subTest(override=list(override)), patch.dict(os.environ, override), \
                    patch('notifications.smtplib.SMTP') as client, \
                    contextlib.redirect_stderr(io.StringIO()) as output:
                notifications.notify_failures('sync', 'recent', [('roms_hiig', 'failed')], '/logs')
            client.assert_not_called()
            self.assertIn('could not be delivered', output.getvalue())
            self.assertNotIn('secret', output.getvalue())

    def test_delivery_errors_and_partial_refusal_are_safe_and_visible(self):
        for partial in (False, True):
            with self.subTest(partial=partial), patch('notifications.smtplib.SMTP') as client, \
                    contextlib.redirect_stderr(io.StringIO()) as output:
                smtp = client.return_value.__enter__.return_value
                if partial:
                    smtp.send_message.return_value = {'ops@example.org': (550, b'smtp-secret')}
                else:
                    smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, b'smtp-secret')
                notifications.notify_failures('sync', 'recent', [('roms_hiig', 'failed')], '/logs')
            self.assertIn('could not be delivered', output.getvalue())
            self.assertNotIn('smtp-secret', output.getvalue())


class JobNotificationTests(unittest.TestCase):
    def setUp(self):
        previous_umask = os.umask(0o077)
        self.addCleanup(os.umask, previous_umask)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cfg = dict(install_root=str(self.root), config_file=str(self.root / 'config.toml'),
                        state_dir=str(self.root / 'state'), bucket='bucket', prefix='pacioos',
                        log_retention_days=30, max_job_seconds=20,
                        datasets={name: dict(store_prefix=f'pacioos/{name}/icechunk')
                                  for name in ('roms_hiig', 'ww3_hawaii')})
        for target, options in [('jobs.load_config', dict(return_value=self.cfg)),
                                ('jobs.activate_environment', {})]:
            mock = patch(target, **options)
            mock.start()
            self.addCleanup(mock.stop)

    def args(self, **overrides):
        return argparse.Namespace(**dict(
            dict(action='sync', config=None, dataset=None, worker=None,
                 scope='recent', dry_run=False, notify=True), **overrides))

    def test_cli_opt_in_and_generated_cron(self):
        for command in (['sync'], ['verify', '--scope', 'full']):
            self.assertFalse(cli.parser()[0].parse_args(command).notify)
            self.assertTrue(cli.parser()[0].parse_args([*command, '--notify']).notify)
        rows = [row for row in jobs.cron_block(self.cfg).splitlines() if not row.startswith('#')]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all('--notify' in row for row in rows))

    def test_aggregate_after_all_datasets_and_never_forward_notify(self):
        for action, scope in [('sync', 'recent'), ('verify', 'full')]:
            with self.subTest(action=action), patch('jobs.notify_failures') as notify:
                def invoke(command, seconds):
                    self.assertNotIn('--notify', command)
                    notify.assert_not_called()
                    return 1
                with patch('jobs.run_bounded', side_effect=invoke) as run:
                    self.assertEqual(jobs.run(self.args(action=action, scope=scope)), 1)
                self.assertEqual(run.call_count, 2)
                expected_details = {}
                for call in run.call_args_list:
                    parsed = cli.parser()[0].parse_args(call.args[0][3:])
                    expected_details[parsed.worker] = dict(unavailable=True, log_path=str(
                        job_reports.log_path(self.cfg, parsed.worker, action, parsed.log_id)))
                notify.assert_called_once_with(action, scope, [
                    ('roms_hiig', 'failed (exit 1)'), ('ww3_hawaii', 'failed (exit 1)')],
                    self.root / 'logs', details=expected_details)

    def test_success_noop_lock_skips_manual_and_dry_run_are_silent(self):
        for codes, options in [([0, 0], {}), ([75, 75], {}), ([1, 1], dict(notify=False)),
                               ([1, 1], dict(dry_run=True))]:
            with self.subTest(codes=codes, options=options), \
                    patch('jobs.run_bounded', side_effect=codes), patch('jobs.notify_failures') as notify:
                self.assertEqual(jobs.run(self.args(**options)), int(any(codes)))
            notify.assert_not_called()
            self.assertFalse((self.root / '.runtime').exists())

    def test_timeout_and_failure_preserve_state_and_skip_only_lock_contention(self):
        with patch('jobs.run_bounded', side_effect=[subprocess.TimeoutExpired('secret', 20), 75]) as run, \
                patch('jobs.notify_failures') as notify, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(jobs.run(self.args()), 1)
        parsed = cli.parser()[0].parse_args(run.call_args_list[0].args[0][3:])
        notify.assert_called_once_with('sync', 'recent', [('roms_hiig', 'timed out')],
            self.root / 'logs', details={'roms_hiig': dict(log_path=str(
                job_reports.log_path(self.cfg, 'roms_hiig', 'sync', parsed.log_id)))})
        self.assertTrue((common.dataset_state(self.cfg, 'roms_hiig') / 'last-timeout.json').exists())

    def test_failed_worker_launch_does_not_prevent_other_datasets(self):
        with patch('jobs.run_bounded', side_effect=[OSError('credential-secret'), 1]) as run, \
                patch('jobs.notify_failures') as notify, contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(jobs.run(self.args()), 1)
        self.assertEqual(run.call_count, 2)
        self.assertNotIn('credential-secret', output.getvalue())
        self.assertEqual(notify.call_args.args[2], [
            ('roms_hiig', 'worker launch failed'), ('ww3_hawaii', 'failed (exit 1)')])

    def test_worker_logs_application_error_without_notifying_and_keeps_recovery_state(self):
        state = common.dataset_state(self.cfg, 'roms_hiig')
        common.atomic_json(state / 'pending-update.json', {'token': 'keep'})
        guidance = 'No cached schema baseline. Run icechunker verify --scope full once.'
        with patch('pipeline.process', side_effect=RuntimeError(guidance)), \
                patch('jobs.notify_failures') as notify, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(jobs.run(self.args(worker='roms_hiig')), 1)
        notify.assert_not_called()
        self.assertIn(guidance, output.getvalue())
        logs = list((self.root / 'logs').glob('*.log'))
        self.assertEqual(len(logs), 1)
        self.assertIn(guidance, logs[0].read_text())
        self.assertEqual(logs[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(common.read_json(state / 'pending-update.json'), {'token': 'keep'})
        self.assertEqual(common.read_json(state / 'last-failure-sync-recent.json')['error'], 'RuntimeError')

    def test_real_worker_lock_skip_is_nonzero_without_alert(self):
        state = common.dataset_state(self.cfg, 'roms_hiig')
        with common.locked(state), patch('pipeline.process') as process, \
                patch('jobs.notify_failures') as notify, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(jobs.run(self.args(worker='roms_hiig')), 75)
        process.assert_not_called()
        notify.assert_not_called()
        self.assertTrue((state / 'last-skip.json').exists())

    def test_smtp_failure_does_not_change_exit_or_failure_and_pending_records(self):
        state = common.dataset_state(self.cfg, 'roms_hiig')
        for name in ('last-failure-sync-recent.json', 'pending-update.json', 'pending-readme.json'):
            common.atomic_json(state / name, {'preserve': name})
        before = {path.name: path.read_bytes() for path in state.iterdir()}
        with patch('jobs.run_bounded', side_effect=[1, 0]), \
                patch.dict(os.environ, SMTP_SETTINGS, clear=True), \
                patch('notifications.smtplib.SMTP', side_effect=OSError('credential-secret')), \
                contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(jobs.run(self.args()), 1)
        self.assertEqual(before, {path.name: path.read_bytes() for path in state.iterdir()})
        self.assertNotIn('credential-secret', output.getvalue())
        self.assertIn('could not be delivered', output.getvalue())
        self.assertFalse((self.root / '.runtime').exists())

    def test_existing_worker_logs_supply_email_details_without_extra_reporting_files(self):
        guidance = 'No cached schema baseline. Run icechunker verify --scope full once.'
        logs = []
        with patch('notifications.send_message') as send:
            def deliver(subject, body):
                self.assertTrue(all(path.is_file() for path in logs))
                raise OSError('smtp-secret')
            send.side_effect = deliver
            def invoke(command, seconds):
                send.assert_not_called()
                parsed = cli.parser()[0].parse_args(command[3:])
                logs.append(job_reports.log_path(self.cfg, parsed.worker, 'sync', parsed.log_id))
                return jobs.worker(self.cfg, self.args(worker=parsed.worker, log_id=parsed.log_id),
                                   parsed.worker)
            with patch('jobs.run_bounded', side_effect=invoke), \
                    patch('pipeline.process', side_effect=[
                        common.RecoveryRequired(guidance), RuntimeError('credential-secret')]), \
                    contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(jobs.run(self.args()), 1)
        send.assert_called_once()
        body = send.call_args.args[1]
        self.assertIn('Error: RecoveryRequired', body)
        self.assertIn('Reason: ' + guidance, body)
        self.assertIn('Error: RuntimeError', body)
        self.assertNotIn('credential-secret', body)
        self.assertIn('could not be delivered', output.getvalue())
        self.assertNotIn('smtp-secret', output.getvalue())
        self.assertNotIn('*.log', body)
        self.assertEqual(len(set(logs)), 2)
        self.assertTrue(all(job_reports.MARKER in path.read_text() for path in logs))
        self.assertTrue(all(str(path) in body for path in logs))
        self.assertFalse((self.root / '.runtime').exists())
        self.assertEqual(len(list(self.root.rglob('*.json'))), 2)
        for name in self.cfg['datasets']:
            state = common.dataset_state(self.cfg, name)
            self.assertTrue((state / 'last-failure-sync-recent.json').exists())

    def test_repeated_dataset_selection_cannot_reuse_an_earlier_worker_report(self):
        with patch('jobs.run_bounded', return_value=1) as run, \
                patch('jobs.notify_failures') as notify, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(jobs.run(self.args(dataset=['roms_hiig', 'roms_hiig'])), 1)
        run.assert_called_once()
        self.assertEqual(notify.call_args.args[2], [('roms_hiig', 'failed (exit 1)')])
        parsed = cli.parser()[0].parse_args(run.call_args.args[0][3:])
        self.assertEqual(notify.call_args.kwargs['details'], {'roms_hiig': dict(unavailable=True,
            log_path=str(job_reports.log_path(self.cfg, 'roms_hiig', 'sync', parsed.log_id)))})

    def test_notification_module_is_shipped_without_tests_or_old_helper(self):
        with tempfile.TemporaryDirectory() as temporary:
            payload = package.build(Path(temporary) / 'payload')
            module = payload / 'app/ops/notifications.py'
            self.assertEqual(module.read_bytes(), Path(notifications.__file__).read_bytes())
            self.assertIn('app/ops/notifications.py', (payload / 'MANIFEST.sha256').read_text())
            self.assertTrue((payload / 'app/ops/job_reports.py').is_file())
            self.assertFalse(list(payload.rglob('test_notifications.py')))
            self.assertFalse(list(payload.rglob('email_notifications.py')))


if __name__ == '__main__':
    unittest.main()
