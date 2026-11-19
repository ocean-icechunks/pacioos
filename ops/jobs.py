#!/usr/bin/env python3
"""Job launcher, worker isolation, logging and explicit user-crontab configuration."""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
from pathlib import Path
import shlex
import subprocess
import sys
import time
import traceback

from common import ROOT, Busy, activate_environment, atomic_json, dataset_state, load_config, locked, run_bounded
import job_reports
from notifications import notify_failures

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
        rows.append(f'{schedule} {command} {action} --notify --config {config}')
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
    logfile = job_reports.log_path(cfg, name, args.action, getattr(args, 'log_id', None) or stamp)
    with logfile.open('x') as log:
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
                job_reports.write_failure(args, name, exc, log)
                return 1


def run(args):
    notify = (getattr(args, 'notify', False) and not getattr(args, 'dry_run', False)
              and not args.worker and args.action in ('sync', 'verify'))
    cfg = load_config(args.config)
    activate_environment(cfg)
    names = list(dict.fromkeys(args.dataset or cfg['datasets']))
    if any(name not in cfg['datasets'] for name in names):
        raise ValueError('Every selected dataset must be in the configuration')
    if args.action == 'cron':
        print(cron_block(cfg), end='')
        return 0
    if args.action == 'check':
        from pipeline import check_setup
        check_setup(cfg)
        return 0
    if args.worker:
        if args.worker not in names:
            raise ValueError('Worker dataset must be selected')
        return worker(cfg, args, args.worker)
    return run_workers(cfg, args, names, notify)


def run_workers(cfg, args, names, notify):
    failed = False
    failures = []
    details = {}
    for name in names:
        log_id = job_reports.new_log_id() if notify else None
        command = [sys.executable, '-u', str(Path(__file__).with_name('cli.py')), args.action, '--config', cfg['config_file'],
                   '--dataset', name, '--worker', name]
        if args.action == 'verify':
            command.extend(['--scope', args.scope])
        if args.dry_run:
            command.append('--dry-run')
        if log_id:
            command.extend(['--log-id', log_id])
        try:
            code = run_bounded(command, cfg['max_job_seconds'])
        except subprocess.TimeoutExpired:
            state = dataset_state(cfg, name)
            atomic_json(state / 'last-timeout.json', dict(time=datetime.now(timezone.utc).isoformat()))
            print(f'{name}: timed out; its process group was stopped.', file=sys.stderr)
            code = 1
            failures.append((name, 'timed out'))
            if notify:
                details[name] = dict(log_path=str(job_reports.log_path(cfg, name, args.action, log_id)))
        except OSError:
            print(f'{name}: worker could not be started; check runtime and permissions.', file=sys.stderr)
            code = 1
            failures.append((name, 'worker launch failed'))
            if notify:
                details[name] = dict(log_path=str(job_reports.log_path(cfg, name, args.action, log_id)))
        else:
            if code not in (0, 75):
                failures.append((name, f'failed (exit {code})'))
                if notify:
                    details[name] = job_reports.read_failure(cfg, args, name, log_id)
        failed |= code != 0
    if notify and failures:
        notify_failures(cfg, args.action, args.scope, failures,
                        Path(cfg['install_root']) / 'logs', details=details)
    return 1 if failed else 0
