"""Standard-library configuration and durable state for local scheduled jobs."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import tomllib

from layout import environment, installation_root, managed_path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = 'https://data.source.coop'


def path(value):
    return Path(os.path.expandvars(str(value))).expanduser().resolve()


def read_json(filename, default=None):
    return json.loads(Path(filename).read_text()) if Path(filename).exists() else default


def atomic_json(filename, value):
    filename = Path(filename)
    filename.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.' + filename.name, dir=filename.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(value, out, indent=2, allow_nan=False)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, filename)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_config(filename=None):
    runtime = read_json(Path(os.environ.get('ICECHUNKER_ROOT', '~/icechunker')).expanduser() / '.runtime/installed.json', {})
    install = installation_root(runtime.get('install_root') or os.environ.get('ICECHUNKER_ROOT') or '~/icechunker')
    filename = Path(managed_path(install, filename or runtime.get('config', 'config/config.toml'), 'Config file'))
    with filename.open('rb') as source:
        cfg = tomllib.load(source)
    cfg['config_file'] = str(filename)
    cfg['install_root'] = install
    for key, default in [('state_dir', runtime.get('state_dir', 'state')),
                         ('rclone', runtime.get('rclone', '.runtime/bin/rclone')),
                         ('key_file', filename.parent / 'source-coop.key')]:
        value = cfg.get(key, default)
        if not value:
            raise ValueError(f'Configure {key}, or run bootstrap first')
        cfg[key] = managed_path(install, value, key)
    cfg.setdefault('bucket', 'ocean-icechunks')
    cfg.setdefault('prefix', 'pacioos')
    cfg.setdefault('role_arn', 'arn:aws:iam::ocean-icechunks:role/FullAccess')
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]*', cfg['bucket']):
        raise ValueError('Invalid bucket')
    if not re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*', cfg['prefix']):
        raise ValueError('Invalid prefix')
    defaults = dict(upload_parallel=1, scan_processes=2, minimum_age_minutes=15,
                    max_upload_batches=3, max_job_seconds=7200, verify_lookback_days=3,
                    verify_samples=8, max_run_age_hours=72, log_retention_days=30)
    for key, default in defaults.items():
        cfg.setdefault(key, default)
        if type(cfg[key]) is not int or cfg[key] < 1:
            raise ValueError(f'{key} must be a positive integer')
    if cfg['verify_samples'] < 4:
        raise ValueError('verify_samples must be at least 4')
    datasets = cfg.get('datasets', {})
    if not datasets:
        raise ValueError('Configure at least one dataset')
    for name, settings in datasets.items():
        if name not in ('roms_hiig', 'ww3_hawaii', 'wrf_hi', 'roms_hiig_reanalysis'):
            raise ValueError(f'Unsupported dataset: {name}')
        settings.setdefault('update_store', name in ('roms_hiig', 'ww3_hawaii'))
        if type(settings['update_store']) is not bool:
            raise ValueError('update_store must be a TOML boolean')
        if name in ('wrf_hi', 'roms_hiig_reanalysis') and settings['update_store']:
            raise ValueError(f'{name} does not have a store updater yet')
        settings['source_dir'] = str(path(settings['source_dir']))
        settings.setdefault('store_prefix', f'{cfg["prefix"]}/{name}/icechunk')
        if not re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*', settings['store_prefix']):
            raise ValueError('Invalid store_prefix')
    for key in ('state_dir', 'config_file', 'rclone', 'key_file'):
        if '\n' in cfg[key] or '%' in cfg[key]:
            raise ValueError('Paths cannot contain newline or %')
    state = Path(cfg['state_dir'])
    if state.is_relative_to('/tmp') or state.is_relative_to('/var/tmp'):
        raise ValueError('state_dir must survive restarts, outside /tmp and /var/tmp')
    return cfg


def activate_environment(cfg):
    """Keep caches/temp files inside the root even when jobs.py is invoked directly."""
    os.environ.update(environment(cfg['install_root']))
    os.environ.pop('SSLKEYLOGFILE', None)
    tempfile.tempdir = None
    os.chdir(cfg['install_root'])


def dataset_state(cfg, name):
    identity = f'{cfg["bucket"]}/{cfg["prefix"]}/{cfg["datasets"][name]["store_prefix"]}'
    digest = hashlib.sha256(identity.encode()).hexdigest()[:12]
    target = Path(cfg['state_dir']) / f'{name}-{digest}'
    root = cfg.get('install_root')
    return Path(managed_path(root, target, 'Dataset state')) if root else target


class Busy(RuntimeError):
    pass


class RecoveryRequired(RuntimeError):
    """Application-owned recovery guidance safe for email; never wrap external error text."""


@contextlib.contextmanager
def locked(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / 'job.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Busy('another sync or verification holds the dataset lock') from exc
        yield


def run_bounded(command, seconds, **kwargs):
    """Kill the entire worker group on timeout, including upload and scanner children."""
    with subprocess.Popen(command, start_new_session=True, **kwargs) as proc:
        try:
            return proc.wait(timeout=seconds)
        except BaseException:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            raise
