# stores/

Code for the virtual Icechunk stores over the NetCDF copies on Source Cooperative. So far there
is only the **smoke test** behind issues #10–#14; there is no production build yet, and nothing
here writes to Source Cooperative.

| File | What |
| --- | --- |
| `pacioos_virtual.py` | Computed references: header scans (NetCDF-3 via kerchunk, HDF5 via h5py), the THREDDS "best" rule, `ManifestArray`s with one 2-D plane per chunk, repository config |
| `smoke_test.py` | Builds a few runs of each product into local repos, reopens them read-only, and compares sampled planes with netCDF-C reads |
| `survey_formats.py` | Reads 8 bytes of every copied file: NetCDF-3 or HDF5, and the NetCDF-3 record count |
| `requirements.txt` | What the scripts need, checked in a clean venv |
| `roms_hiig_reanalysis/` | Reanalysis v2.0 store (#11): `reanalysis-smoke-test-local.ipynb`, a local smoke test with its run saved, and its `requirements.txt` |

```bash
/srv/conda/bin/python3.12 -m venv ~/venvs/pacioos
~/venvs/pacioos/bin/pip install --no-cache-dir -r stores/requirements.txt
~/venvs/pacioos/bin/python -I stores/smoke_test.py /tmp/pacioos-smoke   # about 1.5 minutes
```

The smoke test reads only the public copies at `https://data.source.coop/ocean-icechunks/pacioos/`,
anonymously. What the file headers showed, and why the code does what it does, is in
[`docs/design/file-headers.md`](../docs/design/file-headers.md).
