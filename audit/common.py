"""Shared pieces of the PacIOOS file audit: the store, the products, a NetCDF-3 header parser."""
from __future__ import annotations

import re
import struct
from pathlib import Path

import numpy as np

OUT = Path(__file__).parent / "out"
BUCKET, ENDPOINT = "ocean-icechunks", "https://data.source.coop"
ROOT = "pacioos/"
URL = f"{ENDPOINT}/{BUCKET}/"

# product -> (filename pattern, expected time step in minutes, the variable sampled by scan_values)
PRODUCTS = {
    "roms_hiig": (r"^hiig_forec_(\d{8})\.nc$", 180, "temp"),
    "roms_hiig_reanalysis": (r"^hiig_his_zlevel_(\d{8})\.nc$", 180, "temp"),
    "wrf_hi": (r"^wrf_hi_(\d{8})\.nc$", 60, "Tair"),
    "ww3_hawaii": (r"^ww3hawaii_(\d{8})\.nc$", 60, "Thgt"),
}
# the folder layout the upload script promises: <product>/netcdf/[<version>/]<year>/<file>
PATH_RE = re.compile(r"^pacioos/(?P<product>[^/]+)/netcdf/(?:(?P<version>v[\d.]+)/)?(?P<year>\d{4})/(?P<name>[^/]+)$")


def store():
    from datetime import timedelta

    from obstore.store import S3Store

    # anonymous; timeouts and retries because single reads occasionally stall
    return S3Store(BUCKET, endpoint=ENDPOINT, region="us-east-1", skip_signature=True,
                   client_options={"timeout": "120s", "connect_timeout": "20s"},
                   retry_config={"max_retries": 6, "retry_timeout": timedelta(seconds=300),
                                 "backoff": {"init_backoff": timedelta(seconds=1),
                                             "max_backoff": timedelta(seconds=30), "base": 2}})


# ------------------------------------------------------------------ NetCDF-3 header
# Adapted from ocean-icechunks/hycom (hycom_virtual.py); independent of kerchunk and scipy.

_NC_TYPES = {1: ("i1", 1), 2: ("S1", 1), 3: (">i2", 2), 4: (">i4", 4), 5: (">f4", 4), 6: (">f8", 8)}


class _Reader:
    def __init__(self, buf: bytes):
        self.buf, self.pos = buf, 0

    def i4(self) -> int:
        (v,) = struct.unpack_from(">i", self.buf, self.pos)
        self.pos += 4
        return v

    def i8(self) -> int:
        (v,) = struct.unpack_from(">q", self.buf, self.pos)
        self.pos += 8
        return v

    def name(self) -> str:
        n = self.i4()
        v = self.buf[self.pos:self.pos + n].decode()
        self.pos += (n + 3) // 4 * 4
        return v

    def values(self, nc_type: int, n: int):
        dtype, size = _NC_TYPES[nc_type]
        raw = self.buf[self.pos:self.pos + n * size]
        if len(raw) < n * size:
            raise EOFError
        self.pos += (n * size + 3) // 4 * 4
        if nc_type == 2:
            return raw.decode("latin1").rstrip("\x00")
        arr = np.frombuffer(raw, dtype)
        return arr[0].item() if n == 1 else arr.tolist()

    def attrs(self) -> dict:
        self.i4()  # NC_ATTRIBUTE tag, or 0 when absent
        out = {}
        for _ in range(self.i4()):
            key = self.name()
            nc_type, n = self.i4(), self.i4()
            out[key] = self.values(nc_type, n)
        return out


def parse_nc3(buf: bytes) -> dict:
    """Parse a NetCDF classic (CDF-1) or 64-bit-offset (CDF-2) header. Raises EOFError if `buf` is short."""
    if buf[:3] != b"CDF" or buf[3] not in (1, 2):
        raise ValueError(f"not a NetCDF-3 file: magic {buf[:4]!r}")
    version = buf[3]
    r = _Reader(buf)
    r.pos = 4
    try:
        numrecs = r.i4()
        r.i4()  # NC_DIMENSION tag
        dims = [(r.name(), r.i4()) for _ in range(r.i4())]
        gattrs = r.attrs()
        r.i4()  # NC_VARIABLE tag
        variables = {}
        for _ in range(r.i4()):
            name = r.name()
            dimids = [r.i4() for _ in range(r.i4())]
            attrs = r.attrs()
            nc_type, vsize = r.i4(), r.i4()
            begin = r.i8() if version == 2 else r.i4()
            is_rec = bool(dimids) and dims[dimids[0]][1] == 0
            variables[name] = dict(
                dims=[dims[i][0] for i in dimids],
                shape=[numrecs if (j == 0 and is_rec) else dims[i][1] for j, i in enumerate(dimids)],
                dtype=_NC_TYPES[nc_type][0], vsize=vsize, begin=begin, record=is_rec, attrs=attrs)
    except struct.error as e:
        raise EOFError from e
    recsize = sum(v["vsize"] for v in variables.values() if v["record"])
    return dict(version=version, numrecs=numrecs, dims=dims, attrs=gattrs, variables=variables,
                header_len=r.pos, recsize=recsize)


def nc3_expected_size(h: dict) -> int:
    """File size the header implies: end of the last fixed variable, or of the last record."""
    fixed_end = max((v["begin"] + v["vsize"] for v in h["variables"].values() if not v["record"]), default=0)
    recs = [v for v in h["variables"].values() if v["record"]]
    if not recs:
        return fixed_end
    first = min(v["begin"] for v in recs)
    # a lone record variable is not padded to 4 bytes; ours always have several
    return max(fixed_end, first + h["numrecs"] * h["recsize"])
