"""Single-installation bootstrap; host Python 3.6+, standard library only."""
import argparse
from contextlib import contextmanager
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile

from layout import environment, installation_root, managed_path

TOOLS = {
    'x86_64': ('amd64', 'x86_64',
        'b00f00b3266c3764413afe599d3ec316f6f43b3e0ea8a0bc1d186d2133e46df7',
        '58ccf5f1792b8a5a88d01bc910ea131a8b3db4a319a17ad5fad75e0845a3e271',
        '213f8d0d2525d66fa8b8a022ecea397847b15c3d42c8bd87470f370b9b3236c0'),
    'aarch64': ('arm64', 'aarch64',
        'ee169016675e23a69d77240565133ff7dbc9b33d16fa8f7053d4af39f1eaeb78',
        '37fbb7c5bc66cf99c12aa881949d216181e201dec449772c4329e56487d61179',
        '17f80519a7d421b197381a56251516a14a86f6a035d685c4d7d2d4b2a1e6917e'),
}



def remove(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(str(path))


def copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(str(source), str(target), symlinks=True)
    else:
        shutil.copy2(str(source), str(target))


@contextmanager
def transaction(root, work, names):
    """Backups are never executed. Restore at original paths on any install failure."""
    backup = work / 'recovery'
    if backup.exists():
        raise ValueError('Unresolved install recovery exists; inspect install-work/recovery before retrying')
    backup.mkdir()
    existed = []
    for name in names:
        target = root / name
        if target.exists():
            copy(target, backup / name)
            existed.append(name)
    (backup / 'journal.json').write_text(json.dumps(dict(names=names, existed=existed)))
    try:
        yield
    except BaseException:
        for name in reversed(names):
            remove(root / name)
            if name in existed:
                copy(backup / name, root / name)
        remove(backup)
        raise
    else:
        remove(backup)


def verify_payload(payload):
    manifest = payload / 'MANIFEST.sha256'
    entries = []
    for line in manifest.read_text().splitlines():
        digest, name = line.split('  ', 1)
        if not name or Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('Unsafe payload manifest path')
        filename = Path(managed_path(payload, name, 'Payload file'))
        if (payload / name).is_symlink() or hashlib.sha256(filename.read_bytes()).hexdigest() != digest:
            raise ValueError('Payload checksum differs: ' + name)
        entries.append(name)
    if len(entries) != len(set(entries)) or not {'bootstrap.sh', 'icechunker', 'README.md',
            'app/ops/install.py', 'app/ops/requirements.lock'}.issubset(entries):
        raise ValueError('Incomplete or duplicate payload manifest')
    actual = {str(p.relative_to(payload)) for p in (payload / 'app').rglob('*') if p.is_file()}
    if actual != {p for p in entries if p.startswith('app/')}:
        raise ValueError('App contains files outside the manifest')
    return entries


def download_binary(work, name, url, checksum, member):
    archive = work / (name + ('.zip' if url.endswith('.zip') else '.tar'))
    subprocess.check_call(['curl', '--fail', '--location', '--proto', '=https', '--tlsv1.2',
        '--retry', '3', '--connect-timeout', '20', '--max-time', '600', url, '-o', str(archive)])
    if hashlib.sha256(archive.read_bytes()).hexdigest() != checksum:
        raise ValueError('Download checksum differs: ' + name)
    if url.endswith('.zip'):
        with zipfile.ZipFile(str(archive)) as z:
            content = z.read(member)
    else:
        with tarfile.open(str(archive)) as t:
            content = t.extractfile(member).read()
    destination = work / name
    destination.write_bytes(content)
    destination.chmod(0o700)
    return destination


def initialize_config(root):
    """Create private operator-editable defaults without replacing existing files."""
    directory = root / 'config'
    managed_path(root, str(directory), 'Config directory')
    for name in ('config.toml', 'source-coop.key'):
        managed_path(root, str(directory / name), 'Config file')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    defaults = [('config.toml', (root / 'app/ops/config.example.toml').read_bytes()),
                ('source-coop.key', b'')]
    for name, content in defaults:
        try:
            descriptor = os.open(str(directory / name), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(descriptor, 'wb') as target:
            target.write(content)


def install(root, payload, with_cli=False, python=None, run=subprocess.check_call):
    """Caller holds the installation lock. Injection of run supports offline failure tests."""
    entries = verify_payload(payload)
    # Validate every existing managed tree before copying or modifying files. Symlinks
    # within an installed venv are allowed only when their targets also stay in root.
    for name in ('app', '.runtime', 'state', 'config', 'logs', 'bootstrap.sh', 'icechunker', 'README.md', 'MANIFEST.sha256'):
        target = root / name
        managed_path(root, str(target), 'Installation path')
        if target.is_dir():
            for child in target.rglob('*'):
                if child.is_symlink():
                    managed_path(root, str(child), 'Installation symlink')
    work = root / '.runtime/install-work'
    work.mkdir(parents=True, exist_ok=True)
    installed_file = root / '.runtime/installed.json'
    old = json.loads(installed_file.read_text()) if installed_file.exists() else {}
    lock_hash = hashlib.sha256((payload / 'app/ops/requirements.lock').read_bytes()).hexdigest()
    venv = root / '.runtime/venv'
    rebuild = old.get('lock_sha256') != lock_hash or not (venv / 'bin/python').exists()
    if python:
        python = managed_path(root, python, 'Python interpreter')
        if old.get('python') != python:
            rebuild = True
    rarch, uarch, rsha, usha, csha = TOOLS[platform.machine()]
    requested = [('rclone', '1.76.0',
        'https://github.com/rclone/rclone/releases/download/v1.76.0/rclone-v1.76.0-linux-' + rarch + '.zip',
        rsha, 'rclone-v1.76.0-linux-' + rarch + '/rclone'),
        ('uv', '0.13.9', 'https://github.com/astral-sh/uv/releases/download/0.13.9/uv-' + uarch + '-unknown-linux-musl.tar.gz',
         usha, 'uv-' + uarch + '-unknown-linux-musl/uv')]
    if with_cli:
        requested.append(('source-coop', '0.3.0',
            'https://github.com/source-cooperative/source-coop-cli/releases/download/v0.3.0/source-coop-cli-' + uarch + '-unknown-linux-gnu.tar.xz',
            csha, 'source-coop-cli-' + uarch + '-unknown-linux-gnu/source-coop'))
    downloads = {}
    for name, version, url, checksum, member in requested:
        if old.get(name + '_version') != version or not (root / '.runtime/bin' / name).exists():
            downloads[name] = download_binary(work, name, url, checksum, member)
    names = ['app', 'bootstrap.sh', 'icechunker', 'README.md', 'MANIFEST.sha256',
             '.runtime/bin', '.runtime/installed.json']
    if rebuild:
        names.extend(['.runtime/venv', '.runtime/python'])
    with transaction(root, work, names):
        tools = root / '.runtime/bin'
        tools.mkdir(exist_ok=True)
        for name, file in downloads.items():
            shutil.copy2(str(file), str(tools / name))
        for child in tools.iterdir():
            if child.name not in {item[0] for item in requested}:
                remove(child)
        for name, _, _, _, _ in requested:
            run([str(tools / name), 'version' if name == 'rclone' else '--version'])
        uv = tools / 'uv'
        if not python:
            if not rebuild and old.get('python'):
                python = old['python']
            else:
                run([str(uv), 'python', 'install', '3.12.12'])
                python = subprocess.check_output([str(uv), 'python', 'find', '--managed-python', '3.12.12'], universal_newlines=True).strip()
        python = managed_path(root, python, 'Managed Python')
        run([python, '-c', 'import sys; assert sys.version_info[:3] == (3,12,12), "Python 3.12.12 required"'])
        if rebuild:
            # Create at the final path. Recovery copies are never used as interpreters.
            run([str(uv), 'venv', '--clear', '--seed', '--python', python, str(venv)])
            command = [str(uv), 'pip', 'sync', '--only-binary', ':all:', '--python', str(venv / 'bin/python'),
                       str(payload / 'app/ops/requirements.lock')]
            run(command[:3] + ['--dry-run'] + command[3:])
            run(command)
        run([str(venv / 'bin/python'), '-m', 'pip', 'check'])
        run([str(venv / 'bin/python'), '-c', 'import icechunk,virtualizarr,zarr,netCDF4,h5py,scipy,boto3'])
        # When bootstrapping a staged fresh payload the application is already at its
        # final path. An upgrade package lives temporarily inside install-work/payload.
        if payload != root:
            remove(root / 'app')
            copy(payload / 'app', root / 'app')
            for name in ('bootstrap.sh', 'icechunker', 'README.md', 'MANIFEST.sha256'):
                shutil.copy2(str(payload / name), str(root / name))
        metadata = dict(status='ready', python=python, lock_sha256=lock_hash,
            installed_at=datetime.utcnow().isoformat() + 'Z', install_root=str(root),
            rclone=str(tools / 'rclone'), uv=str(uv), state_dir=str(root / 'state'),
            config=str(root / 'config/config.toml'))
        metadata['packages'] = dict(line.strip().split('==', 1) for line in
            (root / 'app/ops/requirements.lock').read_text().splitlines() if '==' in line and not line.startswith('#'))
        metadata.update({name + '_version': version for name, version, _, _, _ in requested})
        installed_file.write_text(json.dumps(metadata, indent=2) + '\n')
        for name in ('bootstrap.sh', 'icechunker'):
            (root / name).chmod(0o700)
        initialize_config(root)
    # Nothing active refers to install-work or caches. Keep state and credentials.
    remove(work)
    for name in ('.runtime/cache', '.runtime/tmp'):
        remove(root / name)
        (root / name).mkdir(mode=0o700)
    print('Installation ready: {}\nNext: edit config/config.toml, fill config/source-coop.key, then follow README.md to check and test manually.\nNo jobs ran; no cron entries changed.'.format(root))


def main():
    p = argparse.ArgumentParser(description=__doc__, epilog='Creates missing config/config.toml and an empty private config/source-coop.key. '
        'Existing files are preserved. No credentials, jobs or cron are provisioned. '
        'Stage the manifest payload inside the root first. Later upgrades: .runtime/install-work/payload. '
        'Example: bash ~/icechunker/bootstrap.sh --root ~/icechunker')
    p.add_argument('--payload', required=True, help=argparse.SUPPRESS)
    p.add_argument('--root', default=os.environ.get('ICECHUNKER_ROOT', '~/icechunker'), help='default ~/icechunker')
    p.add_argument('--python', help='optional existing Python 3.12.12 inside root')
    p.add_argument('--with-source-cli', action='store_true', help='install optional pinned Source Cooperative CLI')
    args = p.parse_args()
    root = Path(installation_root(args.root))
    payload = Path(managed_path(root, args.payload, 'Payload'))
    if platform.system() != 'Linux' or platform.machine() not in TOOLS:
        p.error('Linux x86_64 or aarch64 required')
    env = environment(root)
    for folder in ('state', 'state/installation.lock', 'config', 'logs', 'logs/bootstrap.log',
                   '.runtime/install-work', '.runtime/bin', '.runtime/python', '.runtime/venv'):
        managed_path(root, folder, folder)
    (root / 'state').mkdir(parents=True, exist_ok=True, mode=0o700)
    os.environ.update(env)
    os.environ.pop('SSLKEYLOGFILE', None)
    os.chdir(str(root))
    root.chmod(0o700)
    with (root / 'state/installation.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for folder in ('config', 'logs', '.runtime/cache', '.runtime/tmp', '.runtime/run'):
            (root / folder).mkdir(parents=True, exist_ok=True, mode=0o700)
        (root / 'config').chmod(0o700)
        # Keep installation diagnostics in the root, without environment/credential dumps.
        with (root / 'logs/bootstrap.log').open('a', buffering=1) as log:
            print('Bootstrap started: ' + datetime.utcnow().isoformat() + 'Z', file=log)
            try:
                def logged_run(command):
                    print('Checking/installing: ' + Path(command[0]).name, flush=True)
                    return subprocess.check_call(command, stdout=log, stderr=subprocess.STDOUT)
                install(root, payload, args.with_source_cli, args.python, run=logged_run)
            except BaseException as exc:
                print('FAILED: ' + type(exc).__name__ + '; original installation restored if recovery completed.', file=log)
                raise
            print('Bootstrap completed.', file=log)


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except Exception as exc:
        print('Installation failed: {}'.format(exc), file=sys.stderr)
        sys.exit(1)
