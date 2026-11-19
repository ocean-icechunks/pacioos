#!/usr/bin/env python3
"""Build a deliberate static payload. Development-only; never shipped to the server."""
import argparse
import hashlib
from pathlib import Path
import shutil

REPO = Path(__file__).resolve().parents[1]
FILES = {
    'ops/README.md': 'README.md',
    'ops/bootstrap.sh': 'bootstrap.sh',
    'ops/icechunker': 'icechunker',
    'LICENSE': 'app/LICENSE',
}
for filename in ('cli.py', 'install.py', 'layout.py', 'jobs.py', 'job_reports.py', 'notifications.py', 'common.py', 'pipeline.py',
                 'headers.py', 'dataset_readme.py', 'validation.py', 'requirements.lock', 'config.example.toml'):
    FILES['ops/' + filename] = 'app/ops/' + filename
for filename in ('upload_to_source_coop.sh', 'source_coop_credentials.py'):
    FILES['upload/' + filename] = 'app/upload/' + filename
for filename in ('pacioos_virtual.py', 'best_series_update.py', 'icechunk_utils.py',
                 'roms_hiig/build_store.py',
                 'roms_hiig/forecast_store.py', 'roms_hiig/erddap_metadata.json',
                 'ww3_hawaii/build_store.py',
                 'ww3_hawaii/ww3_store.py', 'ww3_hawaii/erddap_metadata.json'):
    FILES['stores/' + filename] = 'app/stores/' + filename


def build(destination, seeds=None):
    destination = Path(destination)
    if destination.exists():
        raise ValueError('Destination must be new')
    destination.mkdir(parents=True, mode=0o700)
    for source, target in FILES.items():
        file = destination / target
        file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / source, file)
        file.chmod(0o700 if target in ('bootstrap.sh', 'icechunker') else 0o600)
    rows = ['{}  {}'.format(hashlib.sha256((destination / target).read_bytes()).hexdigest(), target)
            for target in sorted(FILES.values())]
    (destination / 'MANIFEST.sha256').write_text('\n'.join(rows) + '\n')
    if seeds:
        rows = []
        for dataset in ('roms_hiig', 'ww3_hawaii'):
            for name in ('approved-runs.json', 'reference.json', 'provenance.json', 'scan.jsonl.gz'):
                source = Path(seeds) / dataset / name
                file = destination / 'state/seeds/headers' / dataset / name
                file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, file)
                file.chmod(0o600)
                rows.append('{}  {}'.format(hashlib.sha256(file.read_bytes()).hexdigest(), file.relative_to(destination)))
        (destination / 'state/seeds/MANIFEST.sha256').write_text('\n'.join(rows) + '\n')
    return destination


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('destination')
    p.add_argument('--seeds', help='previously validated public header seed directory')
    args = p.parse_args()
    print(build(args.destination, args.seeds))
