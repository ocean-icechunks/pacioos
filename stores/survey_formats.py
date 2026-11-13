"""Format survey of every copied NetCDF on Source Cooperative: magic bytes and NetCDF-3 numrecs.

Reads 8 bytes per file from the copies (never the PacIOOS server), anonymously.
Run:  python -I survey_formats.py <out.json>
"""
import sys
import asyncio, struct, json, collections
import obstore as obs
from obstore.store import S3Store
s = S3Store("ocean-icechunks", endpoint="https://data.source.coop", region="us-east-1", skip_signature=True)
out = {}
async def head(sem, p):
    async with sem:
        for i in range(4):
            try:
                b = bytes(await obs.get_range_async(s, p, start=0, end=8)); break
            except Exception as e:
                await asyncio.sleep(2)
        if b[:3] == b"CDF": return p, f"nc3v{b[3]}", struct.unpack(">i", b[4:8])[0]
        if b[:4] == b"\x89HDF": return p, "hdf5", None
        return p, repr(b), None
async def main():
    sem = asyncio.Semaphore(64)
    for ds in ["roms_hiig", "wrf_hi", "ww3_hawaii", "roms_hiig_reanalysis"]:
        objs = [o for o in obs.list(s, f"pacioos/{ds}/netcdf/").collect() if o["path"].endswith(".nc")]
        res = await asyncio.gather(*(head(sem, o["path"]) for o in objs))
        sizes = {o["path"]: o["size"] for o in objs}
        out[ds] = [(p, f, n, sizes[p]) for p, f, n in sorted(res)]
        print(ds, len(objs), collections.Counter(f for _, f, _ in res))
asyncio.run(main())
json.dump(out, open(sys.argv[1], "w"))
