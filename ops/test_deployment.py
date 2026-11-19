"""Offline CLI, payload, install transaction and cleanup regression tests."""
import argparse
import contextlib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import cli
import install
import jobs
import package
import pipeline


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.home(), prefix='.icechunker-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = package.build(Path(self.temp.name) / 'root with spaces')
        for name in ('state', 'config', 'logs', '.runtime/cache', '.runtime/tmp', '.runtime/bin', '.runtime/python', '.runtime/venv/bin'):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.env = patch.dict(os.environ, ICECHUNKER_ROOT=str(self.root))
        self.env.start()
        self.addCleanup(self.env.stop)

    def invoke(self, args):
        return subprocess.run([str(self.root / 'icechunker')] + args,
            env={**os.environ, 'HTTPS_PROXY': 'http://127.0.0.1:1', 'HTTP_PROXY': 'http://127.0.0.1:1'},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_all_help_before_bootstrap_without_network_config_or_keys(self):
        for args in ([], ['--help'], ['help'], ['help', 'help']):
            self.assertEqual(self.invoke(args).returncode, 0, args)
        for command in cli.DESCRIPTIONS:
            for args in (['help', command], [command, '--help']):
                result = self.invoke(args)
                self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / 'config/config.toml').exists())
        self.assertEqual(subprocess.call(['bash', str(self.root / 'bootstrap.sh'), '--help'], stdout=subprocess.DEVNULL), 0)

    def test_payload_is_explicit_complete_and_excludes_development(self):
        entries = install.verify_payload(self.root)
        self.assertEqual(set(entries), set(package.FILES.values()))
        for name in entries:
            self.assertNotIn('test_', name)
            self.assertFalse(name.endswith('.ipynb'))
        (self.root / 'app/unexpected.py').write_text('')
        with self.assertRaisesRegex(ValueError, 'outside the manifest'):
            install.verify_payload(self.root)

    def test_status_before_bootstrap_and_no_secret_output(self):
        (self.root / 'config/source-coop.key').write_text('PRIVATE KEY CONTENT')
        result = self.invoke(['status'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Not bootstrapped', result.stdout)
        self.assertNotIn('PRIVATE KEY', result.stdout)

    def test_clean_preview_apply_state_and_live_dependencies_survive(self):
        for name in ('config/key', 'state/pending-update.json', '.runtime/bin/uv', '.runtime/venv/bin/library',
                     '.runtime/cache/junk', '.runtime/tmp/junk'):
            (self.root / name).write_text('keep or clean')
        result = self.invoke(['clean'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / '.runtime/cache/junk').exists())
        result = self.invoke(['clean', '--apply'])
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ('config/key', 'state/pending-update.json', '.runtime/bin/uv', '.runtime/venv/bin/library'):
            self.assertTrue((self.root / name).exists(), name)
        self.assertFalse((self.root / '.runtime/cache/junk').exists())
        self.assertFalse((self.root / '.runtime/tmp/junk').exists())
        self.assertEqual(self.invoke(['help', 'verify']).returncode, 0)

    def test_clean_refuses_lock_and_symlink_escapes(self):
        with (self.root / 'state/installation.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            result = self.invoke(['clean', '--apply'])
            self.assertNotEqual(result.returncode, 0)
        (self.root / '.runtime/cache/escape').symlink_to(self.root.parent)
        result = self.invoke(['clean', '--apply'])
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.root.parent.exists())

    def fake_download(self, work, name, *args):
        file = work / name
        file.write_text('tool')
        file.chmod(0o700)
        return file

    def runner(self, command):
        self.commands.append(command)
        if 'venv' in command:
            (self.root / '.runtime/venv/bin').mkdir(parents=True, exist_ok=True)
            (self.root / '.runtime/venv/bin/python').write_text('fake executable at final path')
        if self.fail and 'sync' in command and '--dry-run' not in command:
            raise RuntimeError('injected wheel install failure')

    def do_install(self, payload=None):
        with patch('install.download_binary', side_effect=self.fake_download), \
             patch('install.subprocess.check_output', return_value=str(self.root / '.runtime/python/python')), \
             contextlib.redirect_stdout(io.StringIO()):
            install.install(self.root, payload or self.root, run=self.runner)

    def test_fresh_repeated_and_changed_dependency_installs(self):
        self.commands, self.fail = [], False
        self.do_install()
        self.assertTrue((self.root / '.runtime/installed.json').exists())
        self.assertFalse((self.root / '.runtime/install-work').exists())
        self.assertEqual(sum('venv' in c for c in self.commands), 1)
        config = self.root / 'config/config.toml'
        key = self.root / 'config/source-coop.key'
        self.assertEqual(config.read_bytes(), (self.root / 'app/ops/config.example.toml').read_bytes())
        self.assertEqual(key.read_bytes(), b'')
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)
        self.assertEqual(config.parent.stat().st_mode & 0o777, 0o700)
        config.write_text('operator configuration')
        key.write_text('operator-provided key')
        self.commands = []
        self.do_install()
        self.assertFalse(any('venv' in c or 'sync' in c for c in self.commands))
        self.assertEqual(config.read_text(), 'operator configuration')
        self.assertEqual(key.read_text(), 'operator-provided key')
        self.assertFalse((self.root / 'releases').exists())
        self.assertEqual(install.verify_payload(self.root), sorted(package.FILES.values()))

    def test_failed_upgrade_restores_original_paths_state_and_commands(self):
        self.commands, self.fail = [], False
        self.do_install()
        key = self.root / 'config/key'
        key.write_text('private')
        pending = self.root / 'state/pending-update.json'
        pending.write_text('pending')
        metadata = (self.root / '.runtime/installed.json').read_bytes()
        previous = (self.root / '.runtime/venv/bin/python').read_bytes()
        incoming = package.build(self.root / '.runtime/install-work/payload')
        lock = incoming / 'app/ops/requirements.lock'
        lock.write_text(lock.read_text() + '\n# test changed lock\n')
        manifest = incoming / 'MANIFEST.sha256'
        rows = []
        for line in manifest.read_text().splitlines():
            _, name = line.split('  ', 1)
            rows.append(hashlib.sha256((incoming / name).read_bytes()).hexdigest() + '  ' + name)
        manifest.write_text('\n'.join(rows) + '\n')
        self.fail = True
        with self.assertRaisesRegex(RuntimeError, 'injected'):
            self.do_install(incoming)
        self.assertEqual((self.root / '.runtime/venv/bin/python').read_bytes(), previous)
        self.assertEqual((self.root / '.runtime/installed.json').read_bytes(), metadata)
        self.assertEqual(key.read_text(), 'private')
        self.assertEqual(pending.read_text(), 'pending')
        self.assertFalse(any('/recovery/' in str(c) for c in self.commands))
        # Installed launcher still handles help at the original path after rollback.
        (self.root / '.runtime/venv/bin/python').chmod(0o600)
        self.assertEqual(self.invoke(['help']).returncode, 0)
        self.fail = False
        self.do_install(incoming)
        self.assertFalse((self.root / '.runtime/install-work').exists())

    def test_transaction_restores_app_after_activation_failure(self):
        before = (self.root / 'app/ops/cli.py').read_bytes()
        work = self.root / '.runtime/install-work'
        work.mkdir()
        with self.assertRaises(RuntimeError):
            with install.transaction(self.root, work, ['app']):
                install.remove(self.root / 'app')
                (self.root / 'app').mkdir()
                raise RuntimeError('activation')
        self.assertEqual((self.root / 'app/ops/cli.py').read_bytes(), before)

    def test_check_has_no_network_or_exchange(self):
        cfg = dict(install_root=str(self.root), rclone=str(self.root / '.runtime/bin/rclone'),
                   key_file=str(self.root / 'config/key'), config_file=str(self.root / 'config/config.toml'),
                   datasets={'roms_hiig': {'source_dir': str(self.root)}})
        for key in ('key_file', 'config_file', 'rclone'):
            Path(cfg[key]).write_text('private')
            Path(cfg[key]).chmod(0o700 if key == 'rclone' else 0o600)
        (self.root / 'config').chmod(0o700)
        with patch('source_coop_credentials.read_key'), patch('source_coop_credentials.exchange', side_effect=AssertionError('network')), \
             patch('urllib.request.urlopen', side_effect=AssertionError('network')), \
             patch('socket.socket.connect', side_effect=AssertionError('network')), \
             contextlib.redirect_stdout(io.StringIO()):
            pipeline.check_setup(cfg)

    def test_installer_rejects_external_log_or_lock_before_writing(self):
        outside = Path(self.temp.name) / 'outside'
        outside.write_text('untouched')
        for relative in ('logs/bootstrap.log', 'state/installation.lock'):
            target = self.root / relative
            target.symlink_to(outside)
            result = subprocess.run(['bash', str(self.root / 'bootstrap.sh'), '--root', str(self.root)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(outside.read_text(), 'untouched')
            target.unlink()

    def test_bootstrap_rejects_payload_checksum_change(self):
        (self.root / 'app/ops/requirements.lock').write_text('unexpected')
        with self.assertRaisesRegex(ValueError, 'checksum differs'):
            install.verify_payload(self.root)

    def test_clean_rejects_symlinked_state_escape(self):
        (self.root / 'state/outside').symlink_to(self.root.parent, target_is_directory=True)
        self.assertNotEqual(self.invoke(['clean', '--apply']).returncode, 0)

    def test_job_dispatch_generates_valid_sync_and_verification_worker_commands(self):
        cfg = dict(config_file=str(self.root / 'config/config.toml'), max_job_seconds=30,
                   datasets={'roms_hiig': {}})
        def invoke(command, seconds):
            parsed = cli.parser()[0].parse_args(command[3:])
            self.assertEqual(parsed.worker, 'roms_hiig')
            self.assertEqual(parsed.dataset, ['roms_hiig'])
            self.assertEqual(seconds, 30)
            if parsed.action == 'sync':
                self.assertTrue(parsed.dry_run)
                self.assertNotIn('--scope', command)
            else:
                self.assertEqual(parsed.scope, 'full')
            return 0
        for action in ('sync','verify'):
            args = argparse.Namespace(action=action,config=None,dataset=None,worker=None,
                scope='full' if action=='verify' else 'recent',dry_run=action=='sync')
            with patch('jobs.load_config',return_value=cfg), patch('jobs.activate_environment'), \
                 patch('jobs.run_bounded',side_effect=invoke):
                self.assertEqual(jobs.run(args),0)

    def test_invalid_dataset_or_worker_is_a_setup_error(self):
        cfg = dict(datasets={'roms_hiig': {}})
        for selected,worker in [(['absent'],None),(['roms_hiig'],'absent')]:
            args = argparse.Namespace(action='sync',config=None,dataset=selected,worker=worker)
            with patch('jobs.load_config',return_value=cfg), patch('jobs.activate_environment'):
                with self.assertRaises(ValueError):
                    jobs.run(args)
