#!/usr/bin/env python3
"""Publish the documentation bundle beside the PacIOOS stores on Source Cooperative.

A store is only self-describing if the code and environment that built it sit next to it, as
for ocean-icechunks/noaa-ohc. This uploads, from this repository's committed files:

    source-coop/README.md         -> pacioos/README.md          (the product README)
    stores/<file>                 -> pacioos/<file>             (shared modules, requirements.txt)
    stores/<dataset>/<file>       -> pacioos/<dataset>/<file>   (store README, requirements.txt,
                                                                 smoke-test notebooks, build and
                                                                 update scripts, saved metadata)

so the published tree mirrors `stores/`, and each dataset's `requirements.txt` still finds
`-r ../requirements.txt`. The builds are scripts (`build_store.py`), not one notebook, so the
scripts and the modules they import are the "production notebook" here.

Run it again after editing any of these files (a README in particular). It uploads only files
committed and unchanged in git, so a published copy always matches a commit. The shared
API-key helper is also published from upload/source_coop_credentials.py to the product root.
Development tests are excluded. Dry runs can preview uncommitted changes without credentials.

Before any upload, README destinations are checked for Icechunker's generated metadata
markers. A managed README stops the entire publication; edit its prose through a separate,
reviewed update that preserves the generated section. Unmanaged README uploads use conditional
multipart completion, so concurrent edits fail instead of being overwritten. Compare live
README prose with git before publishing; this guard does not reconcile manual edits.

What it will not touch, by construction: anything under `netcdf/` (write-once, see AGENTS.md),
`icechunk/` or `viewer/`, and `wrf_hi/`, which the PacIOOS team built and publishes themselves.
`stores/README.md` (about this repository's layout) and `.gitignore` files are not published.

    python publish_bundle.py --dry-run
    python publish_bundle.py

Credentials: `icechunk_utils.get_source_credentials` exchanges a private service-account
API key or uses a logged-in source-coop CLI. Failed API-key exchange never falls back.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))

BUCKET = "ocean-icechunks"
PRODUCT = "pacioos"
DATASETS = ("roms_hiig", "roms_hiig_reanalysis", "ww3_hawaii")
NOT_PUBLISHED = {"stores/README.md"}
FORBIDDEN_PARTS = {"netcdf", "icechunk", "viewer", "wrf_hi"}

# Source Cooperative serves the type given at upload and never infers one; without it a file
# is served as binary/octet-stream. These match what noaa-ohc's bundle is served with.
CONTENT_TYPES = {
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".py": "text/x-python; charset=utf-8",
    ".ipynb": "application/x-ipynb+json",
    ".json": "application/json",
    ".png": "image/png",
}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True,
                          text=True).stdout


def bundle(*, allow_dirty: bool = False) -> list[tuple[Path, str, str]]:
    """(local file, key, content type) for every file to publish."""
    tracked = git("ls-files", "-z", "source-coop/README.md", "stores",
                  "upload/source_coop_credentials.py").split('\0')
    rows = []
    for rel in tracked:
        if not rel:
            continue
        path = Path(rel)
        if (rel in NOT_PUBLISHED or path.name == ".gitignore"
                or path.name.startswith('test_')
                or any(part in ('tests', '__pycache__', '.ipynb_checkpoints') for part in path.parts)):
            continue
        if rel == "source-coop/README.md":
            key = f"{PRODUCT}/README.md"
        elif rel == 'upload/source_coop_credentials.py':
            key = f'{PRODUCT}/source_coop_credentials.py'
        else:
            inner = path.relative_to("stores")
            if len(inner.parts) > 1 and inner.parts[0] not in DATASETS:
                sys.exit(f"{rel}: not in a known dataset folder {DATASETS}; add it or skip it")
            key = f"{PRODUCT}/{inner.as_posix()}"
        assert not FORBIDDEN_PARTS & set(Path(key).parts[1:-1]), key
        ctype = CONTENT_TYPES.get(path.suffix.lower())
        if ctype is None:
            sys.exit(f"{rel}: no content type for {path.suffix!r}; add one to CONTENT_TYPES")
        rows.append((REPO / rel, key, ctype))
    dirty = git("status", "--porcelain", "--", *[str(p.relative_to(REPO)) for p, _, _ in rows])
    if dirty.strip() and not allow_dirty:
        sys.exit("uncommitted changes; commit first so the published copy matches a commit:\n"
                 + dirty)
    return rows


def readme_conditions(s3, rows) -> dict[str, dict[str, str]]:
    """Preflight every README before any upload; retain ETags for concurrency checks."""
    from botocore.exceptions import ClientError
    conditions = {}
    for _, key, _ in rows:
        if Path(key).name != 'README.md':
            continue
        try:
            response = s3.get_object(Bucket=BUCKET, Key=key)
        except ClientError as exc:
            if exc.response['Error']['Code'] != 'NoSuchKey':
                raise
            conditions[key] = {'IfNoneMatch': '*'}
            continue
        body = response['Body']
        try:
            existing = body.read()
        finally:
            body.close()
        # Reject even incomplete markers rather than silently dropping managed metadata.
        if b'<!-- icechunker:global-attributes:' in existing:
            raise ValueError(f'{key}: managed README; publication stopped before any upload. '
                             'Preserve its generated section in a reviewed prose update.')
        conditions[key] = {'IfMatch': response['ETag']}
    return conditions


def upload_readme(s3, path: Path, key: str, ctype: str, condition: dict) -> None:
    """Upload committed bytes using Source Cooperative's multipart requirement."""
    body = path.read_bytes()
    upload_id = s3.create_multipart_upload(
        Bucket=BUCKET, Key=key, ContentType=ctype, CacheControl='public, max-age=300')['UploadId']
    try:
        part = s3.upload_part(Bucket=BUCKET, Key=key, UploadId=upload_id, PartNumber=1, Body=body)
        s3.complete_multipart_upload(
            Bucket=BUCKET, Key=key, UploadId=upload_id,
            MultipartUpload={'Parts': [{'ETag': part['ETag'], 'PartNumber': 1}]}, **condition)
    except BaseException:
        try:
            s3.abort_multipart_upload(Bucket=BUCKET, Key=key, UploadId=upload_id)
        except Exception:
            pass
        raise


def upload(s3, rows) -> None:
    conditions = readme_conditions(s3, rows)
    for path, key, ctype in rows:
        if key in conditions:
            upload_readme(s3, path, key, ctype, conditions[key])
        else:
            s3.upload_file(Filename=str(path), Bucket=BUCKET, Key=key,
                           ExtraArgs={'ContentType': ctype, 'CacheControl': 'public, max-age=300'})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="list the uploads; upload nothing")
    args = ap.parse_args()

    rows = bundle(allow_dirty=args.dry_run)
    commit = git("rev-parse", "--short", "HEAD").strip()
    source = f'working tree preview (HEAD {commit}; upload requires committed files)' if args.dry_run else f'commit {commit}'
    print(f"{len(rows)} files from {source} -> s3://{BUCKET}/{PRODUCT}/")
    for path, key, ctype in rows:
        print(f"  {key:62s} {ctype}")
    if args.dry_run:
        return

    import boto3
    from botocore.config import Config
    from icechunk_utils import get_source_credentials

    creds, expiration = get_source_credentials()
    print(f"Source Cooperative token valid until {expiration.isoformat()}")
    s3 = boto3.client(
        "s3",
        endpoint_url=creds["endpoint_url"],
        region_name=creds["region_name"],
        aws_access_key_id=creds["aws_access_key_id"],
        aws_secret_access_key=creds["aws_secret_access_key"],
        aws_session_token=creds.get("aws_session_token"),
        config=Config(connect_timeout=30, read_timeout=120, retries={'max_attempts': 3},
                      request_checksum_calculation='when_required',
                      response_checksum_validation='when_required',
                      s3={'addressing_style': 'path'}),
    )
    try:
        upload(s3, rows)
    finally:
        s3.close()
    print("uploaded; check anonymously with curl -I https://data.source.coop/"
          f"{BUCKET}/{PRODUCT}/<file>")


if __name__ == "__main__":
    main()
