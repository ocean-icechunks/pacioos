"""Single-root paths and subprocess environment; compatible with host Python 3.6+."""
import os
import shlex
import sys


def canonical(value):
    return os.path.realpath(os.path.expanduser(os.path.expandvars(str(value))))


def managed_path(root, value, label):
    root = canonical(root)
    value = os.path.expanduser(os.path.expandvars(str(value)))
    target = canonical(value if os.path.isabs(value) else os.path.join(root, value))
    if os.path.commonpath([root, target]) != root:
        raise ValueError('{} must stay inside the installation root (including symlinks)'.format(label))
    return target


def installation_root(value):
    root = canonical(value)
    home = canonical(os.path.expanduser('~'))
    if os.path.commonpath([root, home]) == root:
        raise ValueError('Choose a dedicated installation directory, not your home or its parent')
    for temporary in ('/tmp', '/var/tmp'):
        if os.path.commonpath([root, temporary]) == temporary:
            raise ValueError('The installation root must survive restarts, outside /tmp and /var/tmp')
    if '\n' in root or '%' in root:
        raise ValueError('Installation paths cannot contain newline or %')
    return root


def environment(root):
    root = canonical(root)
    directories = {
        'XDG_CACHE_HOME': '.runtime/cache', 'XDG_CONFIG_HOME': 'config/xdg',
        'XDG_DATA_HOME': '.runtime/data', 'XDG_STATE_HOME': 'state/xdg',
        'XDG_RUNTIME_DIR': '.runtime/run', 'TMPDIR': '.runtime/tmp',
        'TEMP': '.runtime/tmp', 'TMP': '.runtime/tmp',
        'UV_CACHE_DIR': '.runtime/cache/uv', 'UV_CREDENTIALS_DIR': 'config/uv',
        'UV_PYTHON_INSTALL_DIR': '.runtime/python', 'UV_PYTHON_BIN_DIR': '.runtime/bin/python-bin',
        'UV_TOOL_DIR': '.runtime/uv-tools', 'UV_TOOL_BIN_DIR': '.runtime/bin',
        'PIP_CACHE_DIR': '.runtime/cache/pip', 'PYTHONPYCACHEPREFIX': '.runtime/cache/pycache',
        'PYTHONUSERBASE': '.runtime/python-user', 'RCLONE_CACHE_DIR': '.runtime/cache/rclone',
        'RCLONE_CONFIG': 'config/rclone/rclone.conf',
        'SOURCE_COOP_CREDS_CACHE': '.runtime/cache/source-coop/credentials/_default.json',
        'AWS_CONFIG_FILE': 'config/aws/config',
        'AWS_SHARED_CREDENTIALS_FILE': 'config/aws/credentials', 'BOTO_CONFIG': 'config/boto/config',
    }
    result = {key: managed_path(root, value, key) for key, value in directories.items()}
    result.update(ICECHUNKER_ROOT=root, PYTHONNOUSERSITE='1', PYTHONUNBUFFERED='1',
                  PIP_CONFIG_FILE='/dev/null', UV_NO_CONFIG='1', UV_NO_MODIFY_PATH='1',
                  UV_KEYRING_PROVIDER='disabled', AWS_EC2_METADATA_DISABLED='true')
    return result


def shell_environment(root):
    return '\n'.join('export {}={}'.format(key, shlex.quote(value))
                     for key, value in sorted(environment(root).items())) + '\nunset SSLKEYLOGFILE\n'


def main():
    action, root = sys.argv[1:3]
    root = installation_root(root)
    if action == 'environment':
        print(shell_environment(root), end='')
        return
    if action == 'path':
        print(managed_path(root, sys.argv[3], sys.argv[4]))
        return
    if action != 'bootstrap':
        raise ValueError('Unknown layout action')
    state, config, interpreter = sys.argv[3:6]
    assignments = dict(install_root=root,
                       state_root=managed_path(root, state or 'state', 'State directory'),
                       config_root=managed_path(root, config or 'config', 'Config directory'),
                       python_bin=managed_path(root, interpreter, 'Python interpreter') if interpreter else '')
    if len(sys.argv) > 6:
        managed_path(root, sys.argv[6], 'Setup source directory')
    # Validate all auxiliary paths before bootstrap creates anything, including existing symlinks.
    environment(root)
    for directory in ('app', '.runtime', 'logs', 'state', 'config'):
        managed_path(root, directory, directory)
    managed_path(root, os.path.join(assignments['config_root'], 'config.toml'), 'Config file')
    for key, value in assignments.items():
        if '\n' in value or '%' in value:
            raise ValueError('Paths cannot contain newline or %')
        print('{}={}'.format(key, shlex.quote(value)))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, IndexError) as exc:
        print('Layout error: {}'.format(exc), file=sys.stderr)
        sys.exit(2)
