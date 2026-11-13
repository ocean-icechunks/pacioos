#!/usr/bin/env python
"""Read every .md5 sidecar and compare it with its NetCDF's name and, where possible, its ETag.

For an object uploaded in one part, the S3 ETag is the MD5 of its bytes, so for those files
the sidecar can be checked against the stored bytes without downloading them. Multipart
uploads have an ETag of the form `<hash>-<parts>` and cannot be checked this way; their
bytes were checked by sampled downloads when they were copied (upload/README.md).

Writes out/md5.parquet.

    python -I audit/scan_md5.py
"""
import asyncio
import re
import sys
from pathlib import Path

import obstore as obs
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from common import OUT, store

LINE = re.compile(r"^([0-9a-f]{32})  (\S+)\n?$")


async def main():
    st = store()
    inv = pd.read_parquet(OUT / "inventory.parquet")
    side = inv[inv.kind == "md5"]
    nc = inv[inv.kind == "nc"].set_index("path")
    sem = asyncio.Semaphore(64)

    async def read(p):
        async with sem:
            r = await obs.get_async(st, p)
            return p, bytes(await r.bytes_async()).decode("utf-8", "replace")

    texts = dict(await asyncio.gather(*(read(p) for p in side.path)))
    rows = []
    for p in nc.index:
        sp = p + ".md5"
        t = texts.get(sp)
        m = LINE.match(t) if t is not None else None
        etag = nc.at[p, "etag"]
        rows.append(dict(path=p, has_md5=t is not None, md5_format_ok=bool(m),
                         md5=m.group(1) if m else None, md5_name=m.group(2) if m else None,
                         name_matches=bool(m) and m.group(2) == p.rsplit("/", 1)[-1],
                         etag=etag, multipart="-" in etag,
                         etag_matches=(m.group(1) == etag) if (m and "-" not in etag) else None))
    orphans = sorted(set(side.path) - {p + ".md5" for p in nc.index})
    df = pd.DataFrame(rows)
    df.to_parquet(OUT / "md5.parquet", index=False)
    df["product"] = df.path.str.split("/").str[1]
    print(df.groupby("product").agg(files=("path", "size"), has_md5=("has_md5", "sum"), format_ok=("md5_format_ok", "sum"),
                                    name_ok=("name_matches", "sum"), single_part=("multipart", lambda s: int((~s).sum())),
                                    etag_ok=("etag_matches", lambda s: int(s.fillna(False).astype(bool).sum()))).to_string())
    print("sidecars with no NetCDF:", orphans[:10], len(orphans))


asyncio.run(main())
