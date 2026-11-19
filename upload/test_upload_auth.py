"""Offline checks for key validation and the SSH credential boundary."""

from pathlib import Path
import os
import subprocess
import tempfile
import unittest
import zlib

from source_coop_credentials import read_key

HERE = Path(__file__).resolve().parent


def sample_key():
    body = "A" * 30
    number = zlib.crc32(body.encode())
    checksum = ""
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    while number:
        number, digit = divmod(number, 62)
        checksum = alphabet[digit] + checksum
    return "sck_" + body + checksum.zfill(6)


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = self.root / "pacioos.key"
        self.key.write_text(sample_key() + "\n")
        self.key.chmod(0o600)

    def test_valid_key(self):
        self.assertEqual(read_key(self.key), sample_key())

    def test_rejects_open_permissions(self):
        self.key.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "accessible"):
            read_key(self.key)

    def test_rejects_symlink(self):
        link = self.root / "link"
        link.symlink_to(self.key)
        with self.assertRaisesRegex(ValueError, "regular file"):
            read_key(link)

    def test_rejects_bad_checksum(self):
        self.key.write_text(sample_key()[:-6] + "000000")
        with self.assertRaisesRegex(ValueError, "checksum"):
            read_key(self.key)

    def run_wrapper(self):
        # Mock STS only; exercise the real helper, shell wrapper and credential
        # serialization. All credential values here are deliberately fake.
        (self.root / "boto3.py").write_text('''
from datetime import datetime, timedelta, timezone
class STS:
    def assume_role_with_web_identity(self, **kwargs):
        assert kwargs['WebIdentityToken'].startswith('sck_')
        return {'Credentials': {
            'AccessKeyId': 'TEST_ACCESS', 'SecretAccessKey': 'TEST_SECRET',
            'SessionToken': "TEST_TOKEN with spaces and 'quotes'",
            'Expiration': datetime.now(timezone.utc) + timedelta(hours=1)}}
def client(*args, **kwargs):
    assert kwargs['endpoint_url'] == 'https://data.source.coop/.sts'
    return STS()
''')
        ssh = self.root / "ssh"
        ssh.write_text('''#!/usr/bin/env python3
import os, sys
from pathlib import Path
Path(os.environ['CAPTURE']).write_text(sys.stdin.read())
print('Finished test: 0 uploaded, 0 failed, 0 left for the next run, 0 changed')
''')
        ssh.chmod(0o700)
        env = dict(os.environ, PATH=str(self.root) + os.pathsep + os.environ['PATH'],
                   PYTHONPATH=str(self.root), SOURCE_COOP_AUTH='api-key',
                   SOURCE_COOP_API_KEY_FILE=str(self.key),
                   LOG_DIR=str(self.root / 'logs'), CAPTURE=str(self.root / 'capture'),
                   MAX_RUNS='1')
        return subprocess.run(['bash', str(HERE / 'upload_over_ssh.sh'),
                               '--dry-run', 'roms_hiig', 'ww3_hawaii'],
                              env=env, text=True, capture_output=True, timeout=15)

    def test_only_temporary_credentials_reach_ssh(self):
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        sent = (self.root / 'capture').read_text()
        self.assertNotIn(sample_key(), sent)
        self.assertIn('export AWS_ACCESS_KEY_ID=TEST_ACCESS', sent)
        prefix = sent.split('export RCLONE=', 1)[0]
        # Shell quoting must preserve token characters exactly.
        check = subprocess.run(['bash', '-c', prefix + '\nprintf %s "$AWS_SESSION_TOKEN"'],
                               capture_output=True, text=True)
        self.assertEqual(check.returncode, 0)
        self.assertEqual(check.stdout, "TEST_TOKEN with spaces and 'quotes'")
        logs = ''.join(p.read_text() for p in (self.root / 'logs').iterdir())
        for secret in (sample_key(), 'TEST_ACCESS', 'TEST_SECRET', 'TEST_TOKEN'):
            self.assertNotIn(secret, logs + result.stdout + result.stderr)

    def test_bad_key_stops_before_ssh(self):
        self.key.chmod(0o644)
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 3)
        self.assertFalse((self.root / 'capture').exists())


if __name__ == '__main__':
    unittest.main()
