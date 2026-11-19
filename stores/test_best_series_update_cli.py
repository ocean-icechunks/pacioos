"""Standalone updaters preserve their errors without sending automation email."""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import best_series_update as updater


class StandaloneTests(unittest.TestCase):
    def test_failures_preserve_error_and_never_send_email(self):
        for error in (RuntimeError('scan failed'), SystemExit('scan stopped'), updater.Stop('unsafe')):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as temporary:
                builder = SimpleNamespace(HERE=Path(temporary), BUCKET='bucket',
                    DESTINATIONS={'scratch': 'scratch'}, scan=Mock(side_effect=error))
                with patch.dict(os.environ, {
                        'PACIOOS_ALERT_EMAIL_TO': 'ops@example.org',
                        'PACIOOS_ALERT_EMAIL_FROM': 'sender@example.org',
                        'PACIOOS_SMTP_HOST': 'smtp.example.org'}), \
                        patch.dict(sys.modules, {'icechunk': SimpleNamespace(set_logs_filter=Mock())}), \
                        patch.object(sys, 'argv', ['update_store.py', '--workdir', temporary]), \
                        patch('smtplib.SMTP') as smtp, patch('smtplib.SMTP_SSL') as smtp_ssl, \
                        patch.object(updater, 'log'):
                    with self.assertRaises(SystemExit if isinstance(error, updater.Stop) else type(error)) as raised:
                        updater.main('test update', builder, Mock())
                if isinstance(error, updater.Stop):
                    self.assertEqual(raised.exception.code, '  stopped: unsafe')
                else:
                    self.assertIs(raised.exception, error)
                smtp.assert_not_called()
                smtp_ssl.assert_not_called()

    def test_retry_diagnostics_keep_error_context(self):
        function = Mock(side_effect=[RuntimeError('Connection reset by peer'), 'ok'])
        with patch.object(updater, 'log') as log, patch.object(updater.time, 'sleep'):
            self.assertEqual(updater.retry(function, 'read', attempts=2), 'ok')
        self.assertIn('Connection reset by peer', str(log.call_args_list))


if __name__ == '__main__':
    unittest.main()
