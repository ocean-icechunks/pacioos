"""Structured failure summaries in the existing worker logs, with safe email extraction."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import traceback
from uuid import uuid4

from common import RecoveryRequired
from layout import managed_path

MARKER = 'ICECHUNKER_FAILURE_JSON '
MAX_MESSAGE = 2048
MAX_RECORD = 65536


def new_log_id():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid4().hex


def log_path(cfg, name, action, log_id):
    if name not in cfg['datasets'] or not re.fullmatch(r'[A-Za-z0-9_]+', name) or action not in ('sync', 'verify'):
        raise ValueError('Invalid worker log dataset/action')
    if not re.fullmatch(r'\d{8}T\d{12}Z(?:-[0-9a-f]{32})?', log_id):
        raise ValueError('Invalid worker log ID')
    target = Path(cfg['install_root']) / 'logs' / f'{name}-{action}-{log_id}.log'
    if target.is_symlink():
        raise ValueError('Worker logs cannot be symlinks')
    return Path(managed_path(cfg['install_root'], target, 'Worker log'))


def write_failure(args, name, error, log):
    if not getattr(args, 'log_id', None):
        return
    try:
        message = str(error) if isinstance(error, RecoveryRequired) else ''
        if len(message) > MAX_MESSAGE:
            message = message[:MAX_MESSAGE - 15] + '... [truncated]'
        frames = traceback.extract_tb(error.__traceback__)
        record = dict(version=1, log_id=f'{name}-{args.action}-{args.log_id}.log', dataset=name, action=args.action,
                      scope=args.scope, error_type=type(error).__name__, message=message,
                      location=frames[-1].name if frames else None)
        log.write('\n' + MARKER + json.dumps(record) + '\n')
        log.flush()
    except Exception:
        print(f'{name}: could not append failure summary; see worker diagnostics.', file=sys.stderr)


def read_failure(cfg, args, name, log_id):
    log = None
    try:
        log = log_path(cfg, name, args.action, log_id)
        if not log.is_file():
            raise OSError('Worker log is absent or not a regular file')
        with log.open('rb') as source:
            size = source.seek(0, os.SEEK_END)
            source.seek(max(0, size - MAX_RECORD))
            raw = source.read(MAX_RECORD)
        lines = raw.splitlines()
        if not raw.endswith(b'\n') or not lines or not lines[-1].startswith(MARKER.encode()):
            raise ValueError('Worker failure summary is absent or incomplete')
        record = json.loads(lines[-1][len(MARKER):])
        expected = dict(version=1, log_id=log.name, dataset=name, action=args.action, scope=args.scope)
        if not isinstance(record, dict) or any(record.get(key) != value for key, value in expected.items()):
            raise ValueError('Worker failure summary identity does not match')
        if not isinstance(record.get('error_type'), str) or len(record['error_type']) > 128 \
                or not record['error_type'].isidentifier():
            raise ValueError('Invalid worker failure type')
        if not isinstance(record.get('message'), str) or len(record['message']) > MAX_MESSAGE:
            raise ValueError('Invalid worker failure message')
        location = record.get('location')
        if location is not None and (not isinstance(location, str) or len(location) > 128
                                     or not (location.isidentifier() or
                                             (location.startswith('<') and location.endswith('>')
                                              and location[1:-1].isidentifier()))):
            raise ValueError('Invalid worker failure location')
        if record['message'] and record['error_type'] != RecoveryRequired.__name__:
            raise ValueError('Unrecognized reportable worker failure')
        return dict(error_type=record['error_type'], location=location, log_path=str(log),
                    message=record['message'] or None)
    except (OSError, ValueError, TypeError, RecursionError):
        print(f'{name}: current worker failure summary unavailable or invalid; see job output/logs.',
              file=sys.stderr)
        return dict(unavailable=True, **(dict(log_path=str(log)) if log else {}))
