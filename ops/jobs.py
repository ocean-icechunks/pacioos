#!/usr/bin/env python3
"""Job launcher, worker isolation, logging and explicit user-crontab configuration."""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import traceback

from common import ROOT, Busy, activate_environment, atomic_json, dataset_state, load_config, locked, run_bounded

BEGIN = '# BEGIN PACIOOS SYNC'
END = '# END PACIOOS SYNC'


def cron_block(cfg):
    config = shlex.quote(cfg['config_file'])
    command = shlex.quote(str(Path(cfg.get('install_root', ROOT)) / 'icechunker'))
    rows = [BEGIN, '# Times use the cron daemon timezone; review before installing.']
    for key, default, action in [
        ('sync_schedule', '17 */3 * * *', 'sync'),
        ('full_verify_schedule', '47 2 * * 0', 'verify --scope full'),
    ]:
        schedule = cfg.get(key, default)
        if not isinstance(schedule, str) or len(schedule.split()) != 5 or not all(
                c in '0123456789* /,-' for c in schedule):
            raise ValueError(f'Invalid five-field numeric cron schedule: {key}')
        if any(c in command + config for c in ('\n', '%')):
            raise ValueError('Cron paths cannot contain newline or %')
        rows.append(f'{schedule} {command} {action} --config {config}')
    return '\n'.join([*rows, END]) + '\n'


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, value):
        for stream in self.streams:
            stream.write(value)
            stream.flush()
        return len(value)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def worker(cfg, args, name):
    state = dataset_state(cfg, name)
    logs = Path(cfg['install_root']) / 'logs'
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    for file in logs.glob('*.log'):
        if file.stat().st_mtime < time.time() - cfg['log_retention_days'] * 86400:
            file.unlink()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    with (logs / f'{name}-{args.action}-{stamp}.log').open('w') as log:
        with contextlib.redirect_stdout(Tee(sys.stdout, log)), contextlib.redirect_stderr(Tee(sys.stderr, log)):
            try:
                with locked(state):
                    from pipeline import process
                    process(cfg, name, state, args.action, args.scope, args.dry_run)
                return 0
            except Busy as exc:
                atomic_json(state / 'last-skip.json', dict(time=stamp, reason=str(exc)))
                print(f'{name}: skipped: {exc}', flush=True)
                return 75
            except Exception as exc:
                # No SDK exception text or subprocess environment can expose credentials here.
                print(f'{name}: FAILED ({type(exc).__name__}); see progress state and log.', flush=True)
                if isinstance(exc, (AssertionError, ValueError, RuntimeError)):
                    print(str(exc), flush=True)
                else:
                    print('Location:', traceback.extract_tb(exc.__traceback__)[-1].name, flush=True)
                atomic_json(state / f'last-failure-{args.action}-{args.scope}.json',
                            dict(time=stamp, error=type(exc).__name__))
                return 1


def run(args):
    cfg = load_config(args.config)
    activate_environment(cfg)
    if args.action == 'cron':
        print(cron_block(cfg), end='')
        return 0
    if args.action == 'check':
        from pipeline import check_setup
        check_setup(cfg)
        return 0
    names = args.dataset or list(cfg['datasets'])
    if any(name not in cfg['datasets'] for name in names):
        raise ValueError('Every selected dataset must be in the configuration')
    if args.worker:
        if args.worker not in names:
            raise ValueError('Worker dataset must be selected')
        return worker(cfg, args, args.worker)
    failed = False
    for name in names:
        command = [sys.executable, '-u', str(Path(__file__).with_name('cli.py')), args.action, '--config', cfg['config_file'],
                   '--dataset', name, '--worker', name]
        if args.action == 'verify':
            command.extend(['--scope', args.scope])
        if args.dry_run:
            command.append('--dry-run')
        try:
            code = run_bounded(command, cfg['max_job_seconds'])
        except subprocess.TimeoutExpired:
            state = dataset_state(cfg, name)
            atomic_json(state / 'last-timeout.json', dict(time=datetime.now(timezone.utc).isoformat()))
            print(f'{name}: timed out; its process group was stopped.', file=sys.stderr)
            code = 1
        failed |= code != 0
    return 1 if failed else 0
