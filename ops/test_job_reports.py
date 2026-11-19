"""Structured summaries reuse exact current-run logs without scraping arbitrary output."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import common
import job_reports


class ReportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cfg = dict(install_root=str(self.root), datasets={'roms_hiig': {}})
        self.log_id = job_reports.new_log_id()
        self.args = argparse.Namespace(action='sync', scope='recent', log_id=self.log_id)
        self.log = job_reports.log_path(self.cfg, 'roms_hiig', 'sync', self.log_id)
        self.log.parent.mkdir()

    def write(self, error):
        with self.log.open('w') as log:
            log.write('Existing stdout/stderr diagnostics\n')
            try:
                raise error
            except Exception as exc:
                job_reports.write_failure(self.args, 'roms_hiig', exc, log)
        return json.loads(self.log.read_text().splitlines()[-1][len(job_reports.MARKER):])

    def read(self):
        return job_reports.read_failure(self.cfg, self.args, 'roms_hiig', self.log_id)

    def test_summary_reuses_log_and_does_not_copy_arbitrary_exception_text(self):
        record = self.write(RuntimeError('credential-secret'))
        self.assertEqual(record['location'], 'write')
        self.assertEqual(record['log_id'], self.log.name)
        self.assertNotIn('credential-secret', self.log.read_text())
        self.assertIn('Existing stdout/stderr diagnostics', self.log.read_text())
        detail = self.read()
        self.assertEqual(detail['error_type'], 'RuntimeError')
        self.assertEqual(detail['log_path'], str(self.log))
        self.assertIsNone(detail['message'])
        self.assertEqual(list(self.root.rglob('*')), [self.log.parent, self.log])

    def test_explicit_recovery_guidance_is_included_and_bounded(self):
        guidance = 'No cached schema baseline. Run icechunker verify --scope full once.'
        self.write(common.RecoveryRequired(guidance))
        self.assertEqual(self.read()['message'], guidance)
        record = self.write(common.RecoveryRequired('x' * 10000))
        self.assertLessEqual(len(record['message']), job_reports.MAX_MESSAGE)
        self.assertTrue(record['message'].endswith('[truncated]'))
        self.assertEqual(self.read()['message'], record['message'])

    def test_wrong_identity_or_invalid_fields_are_not_used(self):
        record = self.write(RuntimeError('credential-secret'))
        for key, value in [('log_id', 'old.log'), ('dataset', 'ww3_hawaii'), ('action', 'verify'),
                           ('scope', 'full'), ('version', 2), ('error_type', 'bad\nsecret'),
                           ('message', []), ('message', 'credential-secret'), ('location', {})]:
            with self.subTest(field=key):
                self.log.write_text(job_reports.MARKER + json.dumps({**record, key: value}) + '\n')
                with contextlib.redirect_stderr(io.StringIO()) as output:
                    self.assertEqual(self.read(), dict(unavailable=True, log_path=str(self.log)))
                self.assertIn('unavailable or invalid', output.getvalue())
                self.assertNotIn('credential-secret', output.getvalue())

    def test_absent_plain_malformed_partial_and_oversized_summaries_are_explicit(self):
        for content in (None, b'ordinary output\n', job_reports.MARKER.encode() + b'{\n',
                        job_reports.MARKER.encode() + b'[]\n',
                        job_reports.MARKER.encode() + b'[' * 2000 + b']' * 2000 + b'\n',
                        job_reports.MARKER.encode() + b'x' * (job_reports.MAX_RECORD + 1) + b'\n',
                        job_reports.MARKER.encode() + b'{}'):
            with self.subTest(content_size=None if content is None else len(content)):
                if content is not None:
                    self.log.write_bytes(content)
                with contextlib.redirect_stderr(io.StringIO()) as output:
                    self.assertEqual(self.read(), dict(unavailable=True, log_path=str(self.log)))
                self.assertIn('unavailable', output.getvalue())

    def test_large_logs_only_need_the_bounded_summary_at_the_end(self):
        record = self.write(common.RecoveryRequired('Run full verification.'))
        self.log.write_bytes(b'large earlier diagnostics\n' * job_reports.MAX_RECORD
                             + (job_reports.MARKER + json.dumps(record) + '\n').encode())
        self.assertEqual(self.read()['message'], 'Run full verification.')

    def test_old_log_cannot_supply_current_worker_details(self):
        self.write(common.RecoveryRequired('old guidance'))
        old_log = self.log
        self.log_id = job_reports.new_log_id()
        self.args.log_id = self.log_id
        self.log = job_reports.log_path(self.cfg, 'roms_hiig', 'sync', self.log_id)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.read(), dict(unavailable=True, log_path=str(self.log)))
            self.log.write_bytes(old_log.read_bytes())
            self.assertEqual(self.read(), dict(unavailable=True, log_path=str(self.log)))

    def test_path_escapes_and_symlinked_logs_are_rejected(self):
        with self.assertRaises(ValueError):
            job_reports.log_path(self.cfg, 'roms_hiig', 'sync', '../outside')
        outside = self.root / 'private.txt'
        outside.write_text('credential-secret')
        self.log.symlink_to(outside)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.read(), dict(unavailable=True))
        self.assertEqual(outside.read_text(), 'credential-secret')

    def test_manual_workers_do_not_append_structured_summaries(self):
        self.args.log_id = None
        with self.log.open('w') as log:
            log.write('existing diagnostics\n')
            job_reports.write_failure(self.args, 'roms_hiig', RuntimeError('failed'), log)
        self.assertEqual(self.log.read_text(), 'existing diagnostics\n')

    def test_summary_write_failures_are_reported_without_replacing_processing_failure(self):
        log = Mock(name=str(self.log))
        log.name = str(self.log)
        log.write.side_effect = OSError('credential-secret')
        with contextlib.redirect_stderr(io.StringIO()) as output:
            job_reports.write_failure(self.args, 'roms_hiig', RuntimeError('failed'), log)
        self.assertIn('could not append failure summary', output.getvalue())
        self.assertNotIn('credential-secret', output.getvalue())


if __name__ == '__main__':
    unittest.main()
