"""Offline checks for store credential selection and the API-key boundary."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import icechunk_utils as auth


class StoreAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.key = Path(self.temp.name) / "service.key"
        self.key.touch(mode=0o600)
        env = patch.dict(os.environ, {
            "SOURCE_COOP_AUTH": "auto",
            "SOURCE_COOP_API_KEY_FILE": str(self.key),
            "SOURCE_COOP_ROLE_ARN": "test-role",
        })
        env.start()
        self.addCleanup(env.stop)

    def test_api_key_helper_output_is_captured_and_mapped(self):
        temporary = {
            "AccessKeyId": "TEST_ACCESS", "SecretAccessKey": "TEST_SECRET",
            "SessionToken": "TEST_TOKEN", "Expiration": "2099-01-01T00:00:00Z",
        }
        with patch.object(auth.subprocess, "run") as run:
            run.return_value.stdout = json.dumps(temporary)
            creds, expiration = auth.get_source_credentials()
        args, kwargs = run.call_args
        self.assertEqual(args[0][-4:], ["--key-file", str(self.key), "--role-arn", "test-role"])
        self.assertEqual(kwargs["stdout"], subprocess.PIPE)
        self.assertTrue(kwargs["check"])
        self.assertEqual(creds["aws_session_token"], "TEST_TOKEN")
        self.assertEqual(creds["endpoint_url"], "https://data.source.coop")
        self.assertIsNotNone(expiration.tzinfo)

    def test_failed_exchange_does_not_fall_back_to_cli(self):
        with patch.object(auth.subprocess, "run", side_effect=subprocess.CalledProcessError(3, "helper")) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                auth.get_source_credentials()
        self.assertEqual(run.call_count, 1)

    def test_explicit_cache_keeps_cli_identity_in_auto_mode(self):
        cache = Path(self.temp.name) / "cache.json"
        cache.write_text(json.dumps({
            "access_key_id": "CLI_ACCESS", "secret_access_key": "CLI_SECRET",
            "session_token": "CLI_TOKEN", "expiration": "2099-01-01T00:00:00+00:00",
        }))
        with patch.object(auth.subprocess, "run") as run:
            creds, _ = auth.get_source_credentials(str(cache))
        self.assertEqual(run.call_args.args[0], [auth.SOURCE_COOP_CLI, "creds"])
        self.assertEqual(creds["aws_access_key_id"], "CLI_ACCESS")

    def test_invalid_auth_mode_stops_before_subprocess(self):
        with patch.dict(os.environ, {"SOURCE_COOP_AUTH": "invalid"}), patch.object(auth.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                auth.get_source_credentials()
        run.assert_not_called()

    def test_published_layout_finds_and_can_run_sibling_helper(self):
        folder = Path(self.temp.name) / 'product'
        folder.mkdir()
        helper = folder / 'source_coop_credentials.py'
        helper.write_bytes((Path(auth.__file__).resolve().parent.parent /
                            'upload/source_coop_credentials.py').read_bytes())
        temporary = dict(AccessKeyId='TEST_ACCESS', SecretAccessKey='TEST_SECRET',
                         SessionToken='TEST_TOKEN', Expiration='2099-01-01T00:00:00Z')
        with patch.object(auth, '__file__', str(folder / 'icechunk_utils.py')), \
             patch.object(auth.subprocess, 'run') as run:
            run.return_value.stdout = json.dumps(temporary)
            creds, _ = auth.get_source_credentials()
        self.assertEqual(run.call_args.args[0][1], str(helper))
        self.assertEqual(creds['aws_session_token'], 'TEST_TOKEN')
        result = subprocess.run([sys.executable, str(helper), '--help'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('--key-file', result.stdout)

    def test_missing_published_helper_fails_without_cli_fallback(self):
        folder = Path(self.temp.name) / 'missing-product'
        folder.mkdir()
        with patch.object(auth, '__file__', str(folder / 'icechunk_utils.py')), \
             patch.object(auth.subprocess, 'run') as run:
            with self.assertRaisesRegex(FileNotFoundError, 'download it beside'):
                auth.get_source_credentials()
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
