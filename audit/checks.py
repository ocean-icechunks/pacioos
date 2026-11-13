#!/usr/bin/env python
"""Run every audit check over the scans and write findings.

Inputs (out/): inventory.parquet, headers.jsonl, md5.parquet, values.parquet, erddap_time_*.csv.
Outputs:
  findings.csv  one row per problem or notable fact
  products.csv  one row per product era: files, bytes, dates, format, layout facts for the store
  runs.csv      one row per file: run start, steps, step, written date (small; for the report)

Each finding has a `category`:
    file       a file that is unreadable, truncated, misnamed, or in an unexpected format
    sidecar    a .md5 problem
    schema     variables, shapes, dtypes, chunks or codecs change within a product
    time       time units, run starts, steps, duplicates, gaps
    coverage   the copies' time coverage against what PacIOOS's ERDDAP serves
    grid       coordinates or the land mask differ between files or products
    values     the data planes sampled by scan_values.py
    metadata   attributes a store would have to repair (does not block a build)
    store      a fact the virtual-icechunk build depends on

    python -I audit/checks.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from common import OUT, PRODUCTS

FINDINGS: list[dict] = []
RUN_DAYS = {"roms_hiig": 7, "wrf_hi": 6, "ww3_hawaii": 7}  # shortest normal run, days


def add(category, check, product, files=(), detail="", n_files=None):
    files = [f.rsplit("/", 1)[-1] for f in files]
    FINDINGS.append(dict(category=category, check=check, product=product,
                         n_files=n_files if n_files is not None else len(files),
                         files=" ".join(files[:6]) + (" ..." if len(files) > 6 else ""), detail=detail))


def decode(values, units):
    unit, since = units.split(" since ")
    t0 = pd.Timestamp(since.replace(" UTC", "").strip())
    return t0 + pd.to_timedelta(np.asarray(values, "f8"), unit={"hours": "h", "minutes": "min", "days": "D"}[unit.strip()])


def signature(h: dict) -> dict:
    """What must agree across files of one array: everything but time length and offsets."""
    vs = {}
    for k, v in h["vars"].items():
        d = {"dtype": v["dtype"], "shape_tail": v["shape"][1:] if v["shape"] else [], "dims": v.get("dims")}
        if h["format"] == "hdf5":
            c = v.get("chunks")
            d.update(chunks_tail=c[1:] if c else None, chunk_time=c[0] if c else None, filters=v["filters"], layout=v["layout"])
        else:
            d.update(record=v["record"])
        vs[k] = d
    return {"format": h["format"], "vars": vs}


def attr_signature(h: dict) -> dict:
    return {k: {a: x for a, x in v["attrs"].items()} for k, v in h["vars"].items()}


def sig_hash(d) -> str:
    return hashlib.md5(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:10]


def history_date(attrs: dict):
    """The date a file says it was written, from `history`, if it carries one."""
    h = str(attrs.get("history", ""))
    for pat, fmt in ((r"Created on \w+, (\w+ \d+, \d{4})", "%B %d, %Y"),
                     (r"^\w{3} (\w{3} +\d+ [\d:]+ \d{4})", "%b %d %H:%M:%S %Y")):
        m = re.search(pat, h)
        if m:
            try:
                return pd.to_datetime(re.sub(" +", " ", m.group(1)), format=fmt.replace("%d", "%d"))
            except ValueError:
                pass
    return pd.NaT


def segments(df: pd.DataFrame, col: str) -> list[tuple]:
    """Consecutive runs of equal `col` values, in date order: (value, first name, last name, n)."""
    out = []
    for _, g in df.groupby((df[col] != df[col].shift()).cumsum(), sort=False):
        out.append((g[col].iloc[0], g.name_date.iloc[0].date(), g.name_date.iloc[-1].date(), len(g)))
    return out


def main():
    inv = pd.read_parquet(OUT / "inventory.parquet")
    heads = {}
    for line in (OUT / "headers.jsonl").open():
        r = json.loads(line)
        if r["path"] not in heads or "error" not in r:
            heads[r["path"]] = r
    md5 = pd.read_parquet(OUT / "md5.parquet").set_index("path")
    vals = pd.read_parquet(OUT / "values.parquet").set_index("path") if (OUT / "values.parquet").exists() else None

    # ------------------------------------------------------------ inventory and names
    nc = inv[inv.kind == "nc"].copy()
    for _, r in inv[~inv.layout_ok].iterrows():
        add("file", "path outside the layout", r["product"], [r.path])
    bad = nc[~nc.name_ok]
    for p, g in bad.groupby("product"):
        add("file", "name does not match the product pattern", p, g.path)
    yr = nc[nc.name_ok & (nc.year.astype(float) != nc.name_date.dt.year)]
    for p, g in yr.groupby("product"):
        add("file", "year folder differs from the date in the name", p, g.path)
    dup = nc[nc.duplicated(["product", "name"], keep=False)]
    for p, g in dup.groupby("product"):
        add("file", "same file name in two folders", p, g.path)
    for p, g in inv[inv.kind == "other"].groupby("product"):
        add("file", "object that is neither a NetCDF nor a .md5", p, g.path)

    # ------------------------------------------------------------ per-file table
    rows = []
    for p, h in heads.items():
        product = p.split("/")[1]
        row = dict(path=p, product=product, size=h["size"], error=h.get("error"), format=h.get("format"))
        if "error" not in h:
            t = decode(h["time"]["values"], h["time_units"])
            idx = h["time"]["index"]
            nt = h["vars"]["time"]["shape"][0]
            step_min = (t[1] - t[0]).total_seconds() / 60 / (idx[1] - idx[0]) if len(idx) > 1 else np.nan
            span_ok = (len(idx) < 2) or ((t[-1] - t[0]).total_seconds() / 60 == step_min * (idx[-1] - idx[0]))
            diffs = np.diff(t.values).astype("timedelta64[m]").astype(int) if h["time"]["full"] else None
            row.update(run_start=t[0], run_end=t[-1], steps=nt, step_min=step_min,
                       regular=bool(span_ok and (diffs is None or len(diffs) == 0 or (diffs == diffs[0]).all())),
                       time_full=h["time"]["full"], time_units=h["time_units"],
                       written=history_date(h.get("attrs", {})),
                       expected_size=h.get("expected_size"), max_data_end=h.get("max_data_end"),
                       sig=sig_hash(signature(h)), attr_sig=sig_hash(attr_signature(h)),
                       gattr_keys=",".join(sorted(h.get("attrs", {}))), nvars=len(h["vars"]),
                       vars=",".join(sorted(k for k, v in h["vars"].items() if len(v["shape"]) >= 3)),
                       endian=next((v["dtype"][0] for k, v in h["vars"].items() if len(v["shape"]) >= 3), None),
                       lat=h["coords"].get("lat", {}).get("hash"), lon=h["coords"].get("lon", {}).get("hash"),
                       depth=h["coords"].get("depth", {}).get("hash"), mask=h["coords"].get("mask", {}).get("hash"),
                       mask_land=h["coords"].get("mask", {}).get("n_zero"))
            if h["format"] == "hdf5":
                ci = [v["chunk_index"] for v in h["vars"].values() if "chunk_index" in v]
                row.update(chunks_missing=sum(c["expected_chunks"] - c["n_chunks"] for c in ci),
                           chunk_sizes=",".join(str(s) for s in sorted({s for c in ci for s in c["chunk_sizes"]})),
                           filters=",".join(sorted({str(f) for v in h["vars"].values() for f in v["filters"]})),
                           groups=",".join(h.get("groups", [])))
        rows.append(row)
    f = pd.DataFrame(rows).merge(nc[["path", "name_date", "etag"]], on="path", how="left").sort_values(["product", "name_date"])
    f["name_date"] = pd.to_datetime(f.name_date)
    for col in ("chunks_missing", "chunk_sizes", "filters", "groups", "max_data_end", "expected_size"):
        if col not in f:
            f[col] = np.nan

    # ------------------------------------------------------------ file integrity
    for p, g in f[f.error.notna()].groupby("product"):
        add("file", "header could not be read", p, g.path, "; ".join(g.error.unique()[:3]))
    missing = set(nc.path) - set(heads)
    if missing:
        add("file", "not scanned", None, sorted(missing))
    n3 = f[f.format.fillna("").str.startswith("nc3")]
    tr = n3[n3["size"] != n3.expected_size]
    for p, g in tr.groupby("product"):
        add("file", "NetCDF-3 size differs from what its header implies (truncated or padded)", p, g.path,
            "; ".join(f"{a}: {b} vs {c}" for a, b, c in zip(g.path.str.rsplit('/', n=1).str[-1], g["size"], g.expected_size))[:300])
    h5 = f[f.format == "hdf5"]
    for p, g in h5[h5.max_data_end > h5["size"]].groupby("product"):
        add("file", "HDF5 chunk extends past end of file (truncated)", p, g.path)
    for p, g in h5[h5.chunks_missing > 0].groupby("product"):
        add("file", "HDF5 chunks not allocated (would read as fill)", p, g.path, f"{int(g.chunks_missing.sum())} chunks")
    for p, g in h5[h5.filters != ""].groupby("product"):
        add("schema", "HDF5 filters present (compressed)", p, g.path, ",".join(g.filters.unique()))
    for p, g in h5[h5.groups.fillna("") != ""].groupby("product"):
        add("schema", "HDF5 subgroups present", p, g.path)

    # ------------------------------------------------------------ sidecars
    m = md5.reindex(nc.path)
    for check, mask in [("NetCDF has no .md5", ~m.has_md5.fillna(False).astype(bool)),
                        (".md5 not in `<hash>  <name>` form", m.has_md5.fillna(False).astype(bool) & ~m.md5_format_ok.fillna(False).astype(bool)),
                        (".md5 names a different file", m.md5_format_ok.fillna(False).astype(bool) & ~m.name_matches.fillna(False).astype(bool)),
                        (".md5 differs from the object's ETag (single-part upload)", m.etag_matches.eq(False))]:
        for p, g in m[mask].groupby(m[mask].index.str.split("/").str[1]):
            add("sidecar", check, p, g.index)
    mp_ = m[m.multipart.fillna(False).astype(bool)]
    for p, g in mp_.groupby(mp_.index.str.split("/").str[1]):
        add("sidecar", "multipart upload: ETag is not an MD5, so .md5 cannot be checked without downloading", p, g.index)

    # ------------------------------------------------------------ products: format eras and schema
    prows = []
    for p, g in f[f.error.isna()].groupby("product"):
        g = g.sort_values("name_date")
        segs = segments(g, "sig")
        if len(segs) > 1:
            add("schema", "file layout changes within the product", p, n_files=len(g),
                detail=" | ".join(f"{s[0]}: {s[1]}..{s[2]} ({s[3]})" for s in segs[:12]) + (" ..." if len(segs) > 12 else ""))
        for sig, sg in g.groupby("sig", sort=False):
            h = heads[sg.path.iloc[0]]
            var3 = {k: v for k, v in h["vars"].items() if len(v["shape"]) >= 3}
            v0 = next(iter(var3.values()))
            prows.append(dict(product=p, sig=sig, files=len(sg), first=sg.name_date.min().date(), last=sg.name_date.max().date(),
                              bytes=int(sg["size"].sum()), format=h["format"], byte_order={">": "big", "<": "little"}[v0["dtype"][0]],
                              time_dim=("UNLIMITED" if v0.get("record") else "fixed") if h["format"] != "hdf5" else "chunked",
                              chunks=str(v0.get("chunks")) if h["format"] == "hdf5" else "contiguous",
                              compressed=bool(sg.filters.fillna("").ne("").any()) if h["format"] == "hdf5" else False,
                              variables=" ".join(sorted(var3)), steps=" ".join(f"{k}:{v}" for k, v in sorted(Counter(sg.steps).items())),
                              start_hours=" ".join(f"{k}Z:{v}" for k, v in sorted(Counter(sg.run_start.dt.hour).items())),
                              time_units=" | ".join(sorted(sg.time_units.unique()))))
        # attribute changes that do not change the layout
        asegs = segments(g, "attr_sig")
        if len(asegs) > len(segs):
            add("metadata", "variable attributes change within the product", p, n_files=len(g),
                detail=f"{len(set(g.attr_sig))} distinct attribute sets in {len(asegs)} stretches")
        gk = Counter(g.gattr_keys)
        if len(gk) > 1:
            add("metadata", "global attribute names differ between files", p, n_files=len(g),
                detail=" | ".join(f"[{k}]: {v}" for k, v in gk.most_common(4)))
    products = pd.DataFrame(prows)

    # ------------------------------------------------------------ time
    for p, g in f[f.error.isna()].groupby("product"):
        g = g.sort_values("name_date")
        units = g.time_units.unique()
        if len(units) > 1:
            add("time", "time units differ between files", p, n_files=len(g),
                detail=" | ".join(f"{u}: {(g.time_units == u).sum()}" for u in units))
        want = PRODUCTS[p][1]
        off = g[(g.step_min != want) & g.step_min.notna()]
        if len(off):
            add("time", f"step is not {want} minutes", p, off.path, ", ".join(map(str, off.step_min.unique()[:5])))
        irr = g[~g.regular]
        if len(irr):
            add("time", "irregular time steps inside a file", p, irr.path)
        lag = (g.run_start.dt.normalize() - g.name_date).dt.days
        if (lag != 0).any():
            add("time", "first time step is not on the date in the file name", p, g.path[lag != 0],
                ", ".join(f"{d} d: {n}" for d, n in sorted(Counter(lag[lag != 0]).items())))
        d = g[g.run_start.duplicated(keep=False)]
        if len(d):
            add("time", "two files start at the same time", p, d.path)
        back = g[g.run_start.diff() <= pd.Timedelta(0)]
        if len(back):
            add("time", "file starts before the previous file (by name)", p, back.path)
        if p == "roms_hiig_reanalysis":
            nxt = g.run_start.shift(-1)
            gap = (nxt - g.run_end).dropna()
            step = pd.Timedelta(minutes=want)
            bad = gap[gap != step]
            if len(bad):
                add("time", "reanalysis files do not join end to end", p, g.path.loc[bad.index],
                    ", ".join(str(x) for x in bad.unique()[:5]))
        else:
            days = pd.date_range(g.name_date.min(), g.name_date.max(), freq="D")
            miss = days.difference(pd.DatetimeIndex(g.name_date))
            add("time", "days with no run", p, n_files=len(miss),
                detail=f"{len(miss)} of {len(days)} days; per year: " +
                       ", ".join(f"{y}: {n}" for y, n in sorted(Counter(miss.year).items())))
            # holes: valid times covered by no run
            ends = g.run_end.cummax().shift()
            hole = g[g.run_start - ends > pd.Timedelta(minutes=want)]
            if len(hole):
                add("coverage", "gap longer than the runs: valid times no run covers", p, hole.path,
                    "; ".join(f"{e:%Y-%m-%d %HZ} -> {s:%Y-%m-%d %HZ}" for e, s in zip(ends[hole.index], hole.run_start))[:600])
            short = g[g.steps < g.steps.mode().iloc[0] * 0.8]
            if len(short):
                add("time", "runs much shorter than usual", p, short.path,
                    ", ".join(f"{a:%Y-%m-%d}: {b}" for a, b in zip(short.name_date, short.steps)))
        late = g[(g.written - g.name_date).dt.days > 3]
        if len(late) and g.written.notna().any():
            add("time", "file written more than 3 days after its date (history)", p, late.path,
                f"written: {', '.join(sorted({str(x.date()) for x in late.written}))[:200]}")
        if g.written.isna().all():
            add("metadata", "no written date in `history`", p, n_files=len(g))

    # ------------------------------------------------------------ coverage against ERDDAP
    for p, g in f[f.error.isna()].groupby("product"):
        path = OUT / f"erddap_time_{p}.csv"
        if not path.exists():
            continue
        e = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(path, skiprows=[1])["time"]).dt.tz_localize(None))
        step = pd.Timedelta(minutes=PRODUCTS[p][1])
        ours = pd.DatetimeIndex(sorted(set().union(*[pd.date_range(a, b, freq=step) for a, b in zip(g.run_start, g.run_end)])))
        lo, hi = max(e[0], ours[0]), min(e[-1], ours[-1])
        e_in, o_in = e[(e >= lo) & (e <= hi)], ours[(ours >= lo) & (ours <= hi)]
        only_e, only_o = e_in.difference(o_in), o_in.difference(e_in)
        detail = (f"ERDDAP {len(e)} steps {e[0]}..{e[-1]}; copies {len(ours)} steps {ours[0]}..{ours[-1]}; "
                  f"over the common span {lo}..{hi}: ERDDAP-only {len(only_e)}, copies-only {len(only_o)}")
        if len(only_e) or len(only_o):
            def spans(ix):
                s = pd.Series(ix); grp = (s.diff() != step).cumsum()
                return "; ".join(f"{x.iloc[0]}+{len(x)}" for _, x in s.groupby(grp))[:400]
            add("coverage", "time axis of the copies differs from ERDDAP's", p,
                detail=detail + (f". ERDDAP-only: {spans(only_e)}" if len(only_e) else "") + (f". copies-only: {spans(only_o)}" if len(only_o) else ""))
        else:
            add("coverage", "time axis of the copies equals ERDDAP's over the common span", p, detail=detail)
        if ours[0] > e[0] or ours[-1] < e[-1]:
            add("coverage", "ERDDAP extends beyond the copies", p,
                detail=f"before: {max(0, int((e < ours[0]).sum()))} steps, after: {int((e > ours[-1]).sum())} steps (newer runs not copied yet)")

    # ------------------------------------------------------------ grids
    ok = f[f.error.isna()]
    for p, g in ok.groupby("product"):
        for c in ("lat", "lon", "depth", "mask"):
            u = g[c].dropna().unique()
            if len(u) > 1:
                add("grid", f"`{c}` differs between files", p, n_files=len(g), detail=" | ".join(f"{x}: {(g[c] == x).sum()}" for x in u))
    roms = ok[ok["product"].str.startswith("roms")]
    for c in ("lat", "lon", "depth", "mask"):
        if roms.groupby("product")[c].first().nunique() > 1:
            add("grid", f"ROMS forecast and reanalysis differ in `{c}`", "roms_hiig*")

    # ------------------------------------------------------------ values
    if vals is not None:
        v = vals.join(f.set_index("path")[["product", "name_date", "mask_land"]])
        for p, g in v.groupby("product"):
            for tag in ("first", "last"):
                allfill = g[g[f"{tag}_n_fill"] == g[f"{tag}_n"]]
                if len(allfill):
                    add("values", f"{tag} step is all fill or NaN", p, allfill.index)
                const = g[(g[f"{tag}_std"] == 0)]
                if len(const):
                    add("values", f"{tag} step is constant", p, const.index)
                oor = g[g[f"{tag}_n_out_of_range"] > 0]
                if len(oor):
                    add("values", f"{tag} step has values outside the plausible range", p, oor.index,
                        f"min {oor[f'{tag}_min'].min():.3g}, max {oor[f'{tag}_max'].max():.3g}")
                if g.mask_land.notna().any():
                    fl = g[g[f"{tag}_n_fill"] != g.mask_land]
                    if len(fl):
                        add("values", f"{tag} step: fill cells differ from the land mask", p, fl.index,
                            ", ".join(f"{a}: {b}" for a, b in Counter(fl[f"{tag}_n_fill"]).most_common(4)))
                else:
                    nf = Counter(g[f"{tag}_n_fill"])
                    if len(nf) > 1:
                        add("values", f"{tag} step: number of fill cells varies between files", p, n_files=len(g),
                            detail=", ".join(f"{a} cells: {b} files" for a, b in nf.most_common(5)))
            stuck = g[g.first_hash == g.last_hash]
            if len(stuck):
                add("values", "first and last steps are identical (stuck run)", p, stuck.index)
            for tag in ("first", "last"):
                d = g[g[f"{tag}_hash"].duplicated(keep=False)]
                if len(d):
                    add("values", f"{tag} step identical in different files (duplicated data)", p, d.index,
                        f"{d[f'{tag}_hash'].nunique()} distinct planes shared")

    # ------------------------------------------------------------ store facts (for the virtual-icechunk build)
    for _, r in products.iterrows():
        add("store", "layout of one format era", r["product"], n_files=r.files,
            detail=f"{r.first}..{r.last}: {r.format}, {r.byte_order}-endian, time {r.time_dim}, chunks {r.chunks}, "
                   f"compressed={r.compressed}; vars {r.variables}")
    for p, g in products.groupby("product"):
        if g.byte_order.nunique() > 1:
            add("store", "byte order changes within the product: the eras cannot share a Zarr array", p,
                detail=" | ".join(f"{a}..{b}: {c}" for a, b, c in zip(g["first"], g["last"], g.byte_order)))
        if g.variables.nunique() > 1:
            add("store", "variable set changes within the product", p,
                detail=" | ".join(f"{a}..{b}: {c}" for a, b, c in zip(g["first"], g["last"], g.variables)))

    pd.DataFrame(FINDINGS).to_csv(OUT / "findings.csv", index=False)
    products.drop(columns="sig").to_csv(OUT / "products.csv", index=False)
    f.drop(columns=["sig", "attr_sig", "etag"]).to_csv(OUT / "runs.csv", index=False)
    print(pd.DataFrame(FINDINGS).groupby(["category", "check"]).size().to_string())


if __name__ == "__main__":
    main()
