"""Tests for reusable SMTP error notifications and updater failure reporting."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]

import best_series_update as bsu
import email_notifications as en


class EmailNotificationTests(unittest.TestCase):
    def test_parses_recipient_string_and_list(self):
        self.assertEqual(
            en.parse_recipient_list(' ops@example.org, team@example.org '),
            ['ops@example.org', 'team@example.org'],
        )
        self.assertEqual(
            en.parse_recipient_list(['ops@example.org', 'team@example.org']),
            ['ops@example.org', 'team@example.org'],
        )

    def test_sends_error_details_over_starttls(self):
        settings = {
            'PACIOOS_ALERT_EMAIL_TO': 'ops@example.org, team@example.org',
            'PACIOOS_SMTP_HOST': 'smtp.example.org',
            'PACIOOS_SMTP_USERNAME': 'mailer',
            'PACIOOS_SMTP_PASSWORD': 'secret',
        }
        error = RuntimeError('scan failed')
        with patch.dict(os.environ, settings, clear=True), \
                patch.object(en.smtplib, 'SMTP') as smtp_client:
            smtp = smtp_client.return_value.__enter__.return_value

            en.email_error(
                'update_store.py', error,
                from_address='pacioos@example.org',
                subject_add='(production)',
                message_add='Product: ROMS forecast',
                reply_to_address='help@example.org',
            )

        smtp_client.assert_called_once_with('smtp.example.org', 587, timeout=30)
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with('mailer', 'secret')
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message['To'], 'ops@example.org, team@example.org')
        self.assertEqual(message['Reply-To'], 'help@example.org')
        self.assertIn('update_store.py: ERROR! (production)', message['Subject'])
        self.assertIn('Product: ROMS forecast', message.get_content())
        self.assertIn('RuntimeError: scan failed', message.get_content())

    def test_invalid_smtp_auth_config_fails_explicitly(self):
        settings = {'PACIOOS_SMTP_HOST': 'smtp.example.org',
                    'PACIOOS_SMTP_USERNAME': 'mailer'}
        with patch.dict(os.environ, settings, clear=True):
            with self.assertRaisesRegex(ValueError, 'set both'):
                en.email_error('update_store.py', RuntimeError('failed'),
                               'ops@example.org', from_address='pacioos@example.org')

    def test_mail_failure_does_not_replace_updater_error(self):
        error = RuntimeError('scan failed')
        bs = SimpleNamespace(
            HERE=Path(tempfile.gettempdir()),
            BUCKET='bucket',
            DESTINATIONS={'scratch': 'scratch', 'production': 'production'},
            scan=Mock(side_effect=error),
        )
        fake_icechunk = SimpleNamespace(set_logs_filter=Mock())
        with patch.dict(os.environ, {'PACIOOS_ALERT_EMAIL_TO': 'ops@example.org'}), \
                patch.dict(sys.modules, {'icechunk': fake_icechunk}), \
                patch.object(sys, 'argv', ['update_store.py', '--workdir', tempfile.gettempdir()]), \
                patch.object(en, 'email_error', side_effect=OSError('SMTP unavailable')), \
                patch.object(en, 'log'), \
                patch.object(bsu, 'log'):
            with self.assertRaises(RuntimeError) as raised:
                bsu.main('test update', bs, lambda *args: None)

        self.assertIs(raised.exception, error)

    def test_unconfigured_email_does_not_consume_updater_error(self):
        error = RuntimeError('scan failed')
        bs = SimpleNamespace(
            HERE=Path(tempfile.gettempdir()),
            BUCKET='bucket',
            DESTINATIONS={'scratch': 'scratch', 'production': 'production'},
            scan=Mock(side_effect=error),
        )
        fake_icechunk = SimpleNamespace(set_logs_filter=Mock())
        with patch.dict(os.environ, {}, clear=True), \
                patch.dict(sys.modules, {'icechunk': fake_icechunk}), \
                patch.object(sys, 'argv', ['update_store.py', '--workdir', tempfile.gettempdir()]), \
                patch.object(en, 'log') as notify_log, \
                patch.object(bsu, 'log'):
            with self.assertRaises(RuntimeError) as raised:
                bsu.main('test update', bs, lambda *args: None)

        self.assertIs(raised.exception, error)
        notify_log.assert_called_once()

    def test_no_email_flag_suppresses_notification_and_preserves_error(self):
        error = RuntimeError('scan failed')
        bs = SimpleNamespace(
            HERE=Path(tempfile.gettempdir()),
            BUCKET='bucket',
            DESTINATIONS={'scratch': 'scratch', 'production': 'production'},
            scan=Mock(side_effect=error),
        )
        fake_icechunk = SimpleNamespace(set_logs_filter=Mock())
        with patch.dict(sys.modules, {'icechunk': fake_icechunk}), \
                patch.object(sys, 'argv', [
                    'update_store.py', '--workdir', tempfile.gettempdir(), '--no-email',
                ]), \
                patch.object(bsu, 'notify_update_error') as send_email, \
                patch.object(bsu, 'log'):
            with self.assertRaises(RuntimeError) as raised:
                bsu.main('test update', bs, lambda *args: None)

        self.assertIs(raised.exception, error)
        send_email.assert_not_called()

    def test_nonzero_system_exit_is_not_consumed(self):
        exit_error = SystemExit('scan failed')
        bs = SimpleNamespace(
            HERE=Path(tempfile.gettempdir()),
            BUCKET='bucket',
            DESTINATIONS={'scratch': 'scratch', 'production': 'production'},
            scan=Mock(side_effect=exit_error),
        )
        fake_icechunk = SimpleNamespace(set_logs_filter=Mock())
        with patch.dict(os.environ, {'PACIOOS_ALERT_EMAIL_TO': 'ops@example.org'}), \
                patch.dict(sys.modules, {'icechunk': fake_icechunk}), \
                patch.object(sys, 'argv', ['update_store.py', '--workdir', tempfile.gettempdir()]), \
                patch.object(bsu, 'notify_update_error') as send_email:
            with self.assertRaises(SystemExit) as raised:
                bsu.main('test update', bs, lambda *args: None)

        self.assertIs(raised.exception, exit_error)
        send_email.assert_called_once()


if __name__ == '__main__':
    unittest.main()
