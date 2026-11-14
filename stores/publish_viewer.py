#!/usr/bin/env python3
"""Build the gridlook browser viewer and publish it beside a PacIOOS store on Source Cooperative.

Adapted from ocean-icechunks/icechunks (publish_viewer.py, 2026-11-14) so this repository runs
on its own: the same code, with PRODUCTS holding the PacIOOS stores. Fix bugs in both places.

gridlook (https://github.com/eeholmes/gridlook, a fork of https://github.com/d70-t/gridlook) is
a WebGL viewer for cloud-hosted Zarr and Icechunk stores. Its production build is a folder of
plain static files, so it runs from any prefix that serves files over HTTPS. The store to open
goes in the URL *fragment* (after ``#``)::

    https://data.source.coop/ocean-icechunks/<viewer prefix>/index.html#icechunk+<store url>::varname=temp

What the host must do, and Source Cooperative does (checked 2026-09-17 in ocean-icechunks/
icechunks): send ``access-control-allow-origin: *`` with ``Range`` allowed, and serve content
types as uploaded, so this script sets them (a browser refuses an ES module served as
``binary/octet-stream``). There is no directory index: links must name ``index.html``. The
edge rejects the default ``Python-urllib`` User-Agent with 403.

A virtual store needs CORS on two hosts, the store's and the referenced files'. For the
PacIOOS stores both are ``data.source.coop``.

Usage
-----
1. Get gridlook (Node 20 or newer)::

       git clone https://github.com/eeholmes/gridlook ~/gridlook
       cd ~/gridlook && npm ci

2. Build and upload. ``--build`` runs the Vite build; without it the script uploads an
   existing ``--dist`` folder::

       python publish_viewer.py --product roms_hiig_reanalysis-scratch --build ~/gridlook --dry-run
       python publish_viewer.py --product roms_hiig_reanalysis-scratch --build ~/gridlook

   ``--prune`` also deletes objects under the viewer prefix that the new build no longer
   contains. It never touches anything outside the viewer prefix.

Credentials: the short-lived Source Cooperative token, through
``icechunk_utils.get_source_credentials`` (the ``source-coop`` CLI). Log in first::

    source-coop login --duration 1d --port 8400
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from icechunk_utils import get_source_credentials

PUBLIC = "https://data.source.coop"

# The main Hawaiian Islands: the model grid spans lat 17.0..24.0, lon -163.8..-152.5.
# `alt` is the camera distance; drag the globe and copy the URL to change it.
_HAWAII_VIEW = "px=0::py=0::alt=4000000::lat=20.5::lon=-158.2"

# One entry per store that gets a viewer (see ocean-icechunks/icechunks for the fields).
PRODUCTS = {
    # The published reanalysis store (issue #11), 2009-01-01 .. 2020-12-28, tag v2.0.
    "roms_hiig_reanalysis": {
        "bucket": "ocean-icechunks",
        "viewer_prefix": "pacioos/roms_hiig_reanalysis/viewer",
        "stores": {
            "": {
                "url": f"{PUBLIC}/ocean-icechunks/pacioos/roms_hiig_reanalysis/icechunk",
                "title": "ROMS Hawaii reanalysis v2.0, 2009-2020",
                "view": f"{_HAWAII_VIEW}::dimIndices_time=0::dimIndices_depth=0",
            },
        },
        "variables": ("temp", "salt", "u", "v", "zeta"),
        "catalog": {
            "path": "static/catalog-extended.json",
            "title": "PacIOOS ROMS Hawaii reanalysis",
        },
    },
    # The scratch copy of the reanalysis store (issue #11): may be rewritten or deleted.
    "roms_hiig_reanalysis-scratch": {
        "bucket": "ocean-icechunks",
        "viewer_prefix": "test-repo/pacioos/roms_hiig_reanalysis/viewer",
        "stores": {
            "": {
                "url": f"{PUBLIC}/ocean-icechunks/test-repo/pacioos/roms_hiig_reanalysis/icechunk",
                "title": "ROMS Hawaii reanalysis v2.0 (SCRATCH copy, 4 days)",
                "view": f"{_HAWAII_VIEW}::dimIndices_time=0::dimIndices_depth=0",
            },
        },
        "variables": ("temp", "salt", "u", "v", "zeta"),
        # Without a catalog the published viewer offers gridlook's 70 demo datasets.
        "catalog": {
            "path": "static/catalog-extended.json",
            "title": "PacIOOS ROMS Hawaii reanalysis (scratch)",
        },
    },
    # The ROMS forecast best-series store (issue #10), 2025-01-01 onward.
    "roms_hiig": {
        "bucket": "ocean-icechunks",
        "viewer_prefix": "pacioos/roms_hiig/viewer",
        "stores": {
            "": {
                "url": f"{PUBLIC}/ocean-icechunks/pacioos/roms_hiig/icechunk",
                "title": "ROMS Hawaii forecast, best time series, 2025-",
                "view": f"{_HAWAII_VIEW}::dimIndices_time=0::dimIndices_depth=0",
            },
        },
        "variables": ("temp", "salt", "u", "v", "zeta"),
        "catalog": {
            "path": "static/catalog-extended.json",
            "title": "PacIOOS ROMS Hawaii forecast",
        },
    },
    # The scratch build of the forecast store (issue #10): may be rewritten or deleted.
    "roms_hiig-scratch": {
        "bucket": "ocean-icechunks",
        "viewer_prefix": "test-repo/pacioos/roms_hiig/viewer",
        "stores": {
            "": {
                "url": f"{PUBLIC}/ocean-icechunks/test-repo/pacioos/roms_hiig/icechunk-build",
                "title": "ROMS Hawaii forecast, best time series (SCRATCH build)",
                "view": f"{_HAWAII_VIEW}::dimIndices_time=0::dimIndices_depth=0",
            },
        },
        "variables": ("temp", "salt", "u", "v", "zeta"),
        "catalog": {
            "path": "static/catalog-extended.json",
            "title": "PacIOOS ROMS Hawaii forecast (scratch)",
        },
    },
}
DEFAULT_DIST = Path("/tmp/gridlook-dist")

# Browsers refuse ES modules served with the wrong type, and refuse to
# stream-compile wasm unless it is application/wasm. Do not rely on the
# platform's mimetypes table for these.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".geojson": "application/geo+json",
    ".wasm": "application/wasm",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
}


def _stores(product: dict) -> dict[str, dict[str, str]]:
    """Normalize `stores` / `store_url` to {label: {url, title, view}}."""
    raw = product.get("stores") or {"": product["store_url"]}
    out = {}
    for label, entry in raw.items():
        if isinstance(entry, str):
            entry = {"url": entry}
        out[label] = {"title": label, "view": "", **entry}
    return out


def _variables(product: dict, entry: dict) -> tuple:
    """A store's own `variables` if it names any, else the product's.

    Stores in one product need not share variable names: noaa-oisst's `daily`
    group has `sst` where its `monthly` group has `sst_mean`.
    """
    return tuple(entry.get("variables") or product.get("variables") or ())


def store_fragment(entry: dict, var: str | None = None) -> str:
    """The part after `#`: the store, an optional variable, then the view."""
    name = f"::varname={var}" if var else ""
    view = f"::{entry['view']}" if entry.get("view") else ""
    return f"icechunk+{entry['url']}{name}{view}"


def viewer_urls(product: dict, prefix: str) -> dict[str, str]:
    """One link per store, or per store and variable if the product names any."""
    base = f"{PUBLIC}/{product['bucket']}/{prefix}/index.html"
    urls = {}
    for label, entry in _stores(product).items():
        variables = _variables(product, entry)
        if not variables:
            urls[label] = f"{base}#{store_fragment(entry)}"
        for var in variables:
            urls[f"{label} {var}".strip()] = f"{base}#{store_fragment(entry, var)}"
    return urls


def write_catalog(product: dict, dist: Path) -> str | None:
    """Replace gridlook's default catalog with one listing only this product.

    gridlook reads `static/catalog-extended.json` on load and offers its entries
    in the dataset picker. Its shipped copy is 70 unrelated demo datasets, which
    is noise beside a single product. Each published viewer therefore gets a
    catalog of its own stores instead.

    Written into the build output, never into the gridlook checkout: the
    checkout stays clean, every build stays traceable to a gridlook commit
    (`build-info.json`), and no other product's viewer is affected.

    A catalog entry's `url` becomes the location hash verbatim, so it carries
    the variable and the opening view with it.
    """
    spec = product.get("catalog")
    if not spec:
        return None
    catalog = {
        "type": "gridlook_catalog",
        "title": spec["title"],
        "datasets": [
            {
                "title": entry["title"],
                "url": store_fragment(entry, next(iter(_variables(product, entry)), None)),
                "format": "Icechunk",
                "access": "direct",
                "grid": "regular",
                "crs": "EPSG:4326",
            }
            for entry in _stores(product).values()
        ],
    }
    path = dist / spec["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, indent=2) + "\n")
    return spec["path"]


_DEFAULT_BEGIN, _DEFAULT_END = "<!-- default-store:begin -->", "<!-- default-store:end -->"


def write_default_store(product: dict, dist: Path) -> str:
    """Make the published viewer open this product's first store when the link names none.

    gridlook hard-codes a demo dataset (`DEFAULT_DATASET` in HashGlobeView.vue) and shows it
    whenever the URL has no `#...` fragment -- so a bare `.../viewer/index.html` opened an
    unrelated Mediterranean dataset instead of the product's own store. The app reads `location.hash` when it
    mounts, and a classic inline script in <head> runs before the deferred module bundle, so
    setting the hash there is enough. `replaceState` adds no history entry.

    Written into the build output only, like the catalog: the gridlook checkout stays clean,
    and the bundle is untouched. Idempotent, because one --dist is reused across products.
    """
    import re

    first = next(iter(_stores(product).values()))
    fragment = store_fragment(first, next(iter(_variables(product, first)), None))
    index = dist / "index.html"
    html = index.read_text()
    html = re.sub(re.escape(_DEFAULT_BEGIN) + ".*?" + re.escape(_DEFAULT_END) + r"\n?", "", html, flags=re.S)
    block = (f"{_DEFAULT_BEGIN}\n    <script>if (location.hash.length < 2) "
             f"history.replaceState(null, \"\", {json.dumps('#' + fragment)});</script>\n    {_DEFAULT_END}\n")
    assert "<head>" in html, "index.html has no <head>"
    index.write_text(html.replace("<head>", "<head>\n    " + block, 1))
    return fragment


def build(gridlook: Path, dist: Path, allow_stale: bool = False) -> None:
    gridlook = gridlook.expanduser().resolve()
    if not (gridlook / "package.json").exists():
        sys.exit(f"{gridlook} is not a gridlook checkout (no package.json)")
    check_checkout_is_current(gridlook, allow_stale)
    if not (gridlook / "node_modules").exists():
        subprocess.run(["npm", "ci"], cwd=gridlook, check=True)
    env = dict(os.environ, NODE_OPTIONS="--max-old-space-size=1500")
    cmd = ["npx", "vite", "build", "--outDir", str(dist), "--emptyOutDir",
           "--sourcemap", "false"]
    print("$", " ".join(cmd), f"  (in {gridlook})")
    subprocess.run(cmd, cwd=gridlook, env=env, check=True)
    write_build_info(gridlook, dist)


def check_checkout_is_current(gridlook: Path, allow_stale: bool) -> None:
    """Refuse to build from a gridlook checkout that is behind its remote.

    A clone is per machine, and the fork's work happens on more than one. On 2026-09-17 all
    three viewers here were built from a clone 98 commits behind eeholmes/gridlook, silently
    missing the log10 transform, the colormap-swatch fix and the CORS diagnosis. `gridlook_commit` in build-info.json recorded
    the commit faithfully, and nobody had a reason to compare it with GitHub.
    """
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=gridlook, capture_output=True, text=True)

    fetch = git("fetch", "--quiet")
    upstream = git("rev-parse", "--abbrev-ref", "@{upstream}").stdout.strip()
    if fetch.returncode != 0 or not upstream:
        problem = f"could not compare {gridlook} with its remote ({fetch.stderr.strip() or 'no upstream branch'})"
    else:
        behind = int(git("rev-list", "--count", f"HEAD..{upstream}").stdout.strip() or 0)
        if behind == 0:
            print(f"gridlook checkout is current with {upstream}")
            return
        problem = (f"{gridlook} is {behind} commit(s) behind {upstream}. "
                   f"Update it first:  git -C {gridlook} pull --ff-only && (cd {gridlook} && npm ci)")
    if allow_stale:
        print(f"WARNING: {problem} -- building anyway (--allow-stale)")
    else:
        sys.exit(f"{problem}\nPass --allow-stale to build from it regardless.")


def write_build_info(gridlook: Path, dist: Path) -> None:
    """Record which gridlook commit is live, so the published copy is traceable."""
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=gridlook, capture_output=True,
                              text=True).stdout.strip()
    info = {
        "gridlook_remote": git("remote", "get-url", "origin"),
        "gridlook_commit": git("rev-parse", "HEAD"),
        "gridlook_dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
        "gridlook_behind_remote": int(git("rev-list", "--count", "HEAD..@{upstream}") or 0),
        "node": subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip(),
        "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (dist / "build-info.json").write_text(json.dumps(info, indent=2) + "\n")


def plan(dist: Path) -> list[tuple[Path, str, str, str]]:
    """(local file, relative key, content type, cache control) for every file."""
    if not (dist / "index.html").exists():
        sys.exit(f"{dist} has no index.html -- build first (--build)")
    rows = []
    for path in sorted(p for p in dist.rglob("*") if p.is_file()):
        rel = path.relative_to(dist).as_posix()
        ctype = (CONTENT_TYPES.get(path.suffix.lower())
                 or mimetypes.guess_type(path.name)[0]
                 or "application/octet-stream")
        if rel == "index.html":
            cache = "no-cache"
        elif rel.startswith("assets/"):
            cache = "public, max-age=31536000, immutable"
        else:
            cache = "public, max-age=300"
        rows.append((path, rel, ctype, cache))
    return rows


def s3_client():
    import boto3

    creds, expiration = get_source_credentials()
    print(f"  Source Cooperative token valid until {expiration.isoformat()}")
    return boto3.client(
        "s3",
        endpoint_url=creds["endpoint_url"],
        region_name=creds["region_name"],
        aws_access_key_id=creds["aws_access_key_id"],
        aws_secret_access_key=creds["aws_secret_access_key"],
        aws_session_token=creds.get("aws_session_token"),
    )


def upload(rows, bucket: str, prefix: str, prune: bool) -> None:
    s3 = s3_client()
    # Assets first, index.html last: a visitor never gets a page whose assets
    # are not up yet.
    for path, rel, ctype, cache in sorted(rows, key=lambda r: r[1] == "index.html"):
        s3.upload_file(
            Filename=str(path), Bucket=bucket, Key=f"{prefix}/{rel}",
            ExtraArgs={"ContentType": ctype, "CacheControl": cache},
        )
        print(f"  put {rel}")
    if prune:
        keep = {f"{prefix}/{rel}" for _, rel, _, _ in rows}
        pages = s3.get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=f"{prefix}/")
        for page in pages:
            for obj in page.get("Contents", []):
                if obj["Key"] not in keep:
                    s3.delete_object(Bucket=bucket, Key=obj["Key"])
                    print(f"  removed stale {obj['Key'][len(prefix) + 1:]}")


def verify(bucket: str, prefix: str) -> None:
    """Anonymous check that the page is public and served with the right type."""
    url = f"{PUBLIC}/{bucket}/{prefix}/index.html?cb={os.getpid()}"
    # Source Cooperative's edge 403s the default Python-urllib User-Agent.
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": "gridlook-publisher"})
    with urllib.request.urlopen(req) as r:
        print(f"  {r.status} {r.headers['Content-Type']}  "
              f"cache-control: {r.headers.get('Cache-Control', '(not echoed)')}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--product", required=True, choices=sorted(PRODUCTS),
                    help="which repo and store to publish the viewer for")
    ap.add_argument("--build", type=Path, metavar="GRIDLOOK_DIR",
                    help="gridlook checkout to build before uploading")
    ap.add_argument("--allow-stale", action="store_true",
                    help="build even if the gridlook checkout is behind its remote")
    ap.add_argument("--dist", type=Path, default=DEFAULT_DIST,
                    help=f"build output folder (default {DEFAULT_DIST})")
    ap.add_argument("--prefix", default=None,
                    help="prefix for the viewer (default: the product's viewer_prefix)")
    ap.add_argument("--dry-run", action="store_true",
                    help="list what would be uploaded; upload nothing")
    ap.add_argument("--prune", action="store_true",
                    help="delete objects under the prefix that this build lacks")
    args = ap.parse_args()
    product = PRODUCTS[args.product]
    prefix = (args.prefix or product["viewer_prefix"]).strip("/")
    bucket = product["bucket"]

    if args.build:
        build(args.build, args.dist, args.allow_stale)
    # Before plan(), so the catalog is part of the upload set.
    written = write_catalog(product, args.dist)
    if written:
        print(f"wrote {written} listing {len(_stores(product))} stores")
    print(f"default store (links with no #fragment): {write_default_store(product, args.dist)}")
    rows = plan(args.dist)
    size = sum(p.stat().st_size for p, *_ in rows)
    print(f"{len(rows)} files, {size / 2**20:.1f} MB -> s3://{bucket}/{prefix}/")

    if args.dry_run:
        for _, rel, ctype, cache in rows:
            print(f"  {rel:55s} {ctype:28s} {cache}")
    else:
        upload(rows, bucket, prefix, args.prune)
        verify(bucket, prefix)

    print("\nViewer links:")
    for var, url in viewer_urls(product, prefix).items():
        print(f"  {var}: {url}")


if __name__ == "__main__":
    main()
