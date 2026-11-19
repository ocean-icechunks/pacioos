"""Icechunker command interface. Help works on host Python 3.6 without dependencies."""
import argparse
import json
import os
from pathlib import Path
import sys

DESCRIPTIONS = {
    'sync': 'Upload immutable copies, validate new/pending transfers and update stores. '
            'Refresh dataset README metadata when changed. No incoming work means no '
            'source-header/science reads or store writes; cached README metadata can still be reconciled.',
    'check': 'Local readiness: config, private key format/permissions, tools/imports and '
             'source-folder access. No network or credential exchange; remote access remains untested.',
    'verify': 'Read published data and record local results; never upload or modify stores. '
              'Recent checks use the past three days plus forecast horizon by default. '
              'Full refreshes every source header and audits the complete coordinate/reference '
              'plan with historical science samples. It does not read every chunk or download '
              'all historical NetCDF bytes. Full verification is intended weekly.',
    'status': 'Show installed versions, paths, last results, pending work and outstanding failures. '
              'Local only; never prints key contents.',
    'cron': 'Print suggested sync and weekly verification entries. Review timezone and install '
            'manually. This command never changes crontab.',
    'clean': 'Preview disposable cache and temporary files. --apply deletes them while holding '
             'the installation lock. Credentials, state, logs, installed dependencies and '
             'failed-install diagnostics are preserved.',
}


class InstallationBusy(ValueError):
    """Expected installation-lock contention, not an operational failure alert."""


def parser():
    p = argparse.ArgumentParser(description='Icechunker: immutable PacIOOS copies and virtual stores.',
        epilog='Root: directory containing icechunker (default deployment ~/icechunker). '
               'Example: ~/icechunker/icechunker help verify. Bootstrap: bash ~/icechunker/bootstrap.sh --help')
    sub = p.add_subparsers(dest='action')
    h = sub.add_parser('help', help='show global or command help')
    h.add_argument('command', nargs='?', choices=list(DESCRIPTIONS) + ['help'])
    for action, description in DESCRIPTIONS.items():
        command = sub.add_parser(action, help=description, description=description,
            epilog='Example: ~/icechunker/icechunker ' + action +
                   (' --scope full --dataset roms_hiig' if action == 'verify' else ''))
        if action in ('sync', 'verify', 'check', 'cron'):
            command.add_argument('--config', help='TOML path inside root (default config/config.toml)')
        if action in ('sync', 'verify'):
            command.add_argument('--dataset', action='append', help='repeat to select configured datasets; default all')
            command.add_argument('--worker', help=argparse.SUPPRESS)
            command.add_argument('--log-id', help=argparse.SUPPRESS)
            command.add_argument('--notify', action='store_true',
                                 help='send one best-effort failure email; no alerts for dry runs or lock skips')
        if action == 'sync':
            command.add_argument('--dry-run', action='store_true', help='list differences; no remote writes (contacts services)')
        if action == 'verify':
            command.add_argument('--scope', choices=['recent', 'full'], default='recent', help='default: recent')
        if action == 'clean':
            command.add_argument('--apply', action='store_true', help='delete the previewed disposable files')
    return p, sub


def local_status(root):
    installed = root / '.runtime/installed.json'
    print('Root: {}\nApp: {}\nConfig: {}\nLogs: {}\nState: {}'.format(
        root, root / 'app', root / 'config/config.toml', root / 'logs', root / 'state'))
    if installed.exists():
        # Whitelist metadata; do not dump arbitrary configuration or credential files.
        value = json.loads(installed.read_text())
        for key in ('status', 'python', 'rclone_version', 'uv_version', 'lock_sha256', 'installed_at'):
            print('{}: {}'.format(key, value.get(key, 'unknown')))
        for name in ('icechunk', 'virtualizarr', 'netCDF4', 'h5py'):
            print('{}: {}'.format(name, value.get('packages', {}).get(name, 'unknown')))
    else:
        print('Not bootstrapped.')
    state = root / 'state'
    for pattern in ('*/last-*.json', '*/pending-update.json', '*/pending-readme.json'):
        for file in sorted(state.glob(pattern)):
            print('{}: {}'.format(file.relative_to(root), file.read_text().strip()))
    return 0


def main(argv=None):
    p, sub = parser()
    args = p.parse_args(argv)
    if args.action in (None, 'help'):
        target = getattr(args, 'command', None)
        (sub.choices[target] if target else p).print_help()
        return 0
    args.scope = getattr(args, 'scope', 'recent')
    args.dry_run = getattr(args, 'dry_run', False)
    args.dataset = getattr(args, 'dataset', None)
    args.worker = getattr(args, 'worker', None)
    try:
        return dispatch(args)
    except InstallationBusy:
        raise
    except Exception as exc:
        if (getattr(args, 'notify', False) and not args.dry_run and not args.worker
                and args.action in ('sync', 'verify')):
            try:
                from common import load_config
                from notifications import notify_failures
                cfg = load_config(getattr(args, 'config', None))
                logs = Path(cfg['install_root']) / 'logs'
                notify_failures(cfg, args.action, args.scope, [
                    ('parent-job', 'failed ({}); selected work may be incomplete'.format(type(exc).__name__))
                ], logs)
            except Exception:
                print('Icechunker: parent failure notification unavailable; inspect job output.',
                      file=sys.stderr)
        raise


def dispatch(args):
    from layout import installation_root, managed_path, environment
    root = Path(installation_root(os.environ.get('ICECHUNKER_ROOT', '~/icechunker')))
    for folder in ('app', '.runtime', 'state', 'config', 'logs'):
        directory = Path(managed_path(root, folder, folder))
        if folder in ('state', 'config') and directory.exists():
            for child in directory.rglob('*'):
                if child.is_symlink():
                    managed_path(root, str(child), 'State/config symlink')
    env = environment(root)
    os.environ.update(env)
    os.environ.pop('SSLKEYLOGFILE', None)
    import tempfile
    tempfile.tempdir = None
    # Shared with bootstrap: no cleanup/install may race a command or its workers.
    import fcntl
    (root / 'state').mkdir(exist_ok=True, mode=0o700)
    with (root / 'state/installation.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, (fcntl.LOCK_EX if args.action == 'clean' else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise InstallationBusy('Installation or another command is busy; retry later')
        if args.action == 'status':
            return local_status(root)
        if args.action == 'clean':
            import shutil
            for name in ('.runtime/cache', '.runtime/tmp'):
                directory = Path(managed_path(root, name, 'Disposable directory'))
                print(('Deleting: ' if args.apply else 'Would delete: ') + str(directory))
                # Reject even interior symlink escapes before deleting anything.
                for item in directory.rglob('*') if directory.exists() else []:
                    managed_path(root, str(item), 'Disposable file')
            if args.apply:
                for name in ('.runtime/cache', '.runtime/tmp'):
                    directory = root / name
                    if directory.exists():
                        shutil.rmtree(str(directory))
                    directory.mkdir(parents=True, mode=0o700)
            return 0
        if sys.version_info < (3, 12):
            raise ValueError('Run bootstrap first; processing requires the managed Python 3.12 environment')
        from jobs import run
        return run(args)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError) as exc:
        print('Setup error: {}'.format(exc), file=sys.stderr)
        sys.exit(2)
