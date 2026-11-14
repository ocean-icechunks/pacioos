# stores/

Code for the virtual Icechunk stores over the NetCDF copies on Source Cooperative.
`smoke_test.py` is the smoke test behind issues #10–#14. The **reanalysis store (#11) is
published**, at `ocean-icechunks/pacioos/roms_hiig_reanalysis/icechunk` (tag `v2.0`), built by
`roms_hiig_reanalysis/build_store.py`. The other products have no store yet.

| File | What |
| --- | --- |
| `pacioos_virtual.py` | Computed references: header scans (NetCDF-3 via kerchunk, HDF5 via h5py), the THREDDS "best" rule, `ManifestArray`s with one 2-D plane per chunk, repository config |
| `smoke_test.py` | Builds a few runs of each product into local repos, reopens them read-only, and compares sampled planes with netCDF-C reads |
| `survey_formats.py` | Reads 8 bytes of every copied file: NetCDF-3 or HDF5, and the NetCDF-3 record count |
| `requirements.txt` | What the scripts need, checked in a clean venv |
| `icechunk_utils.py` | Source Cooperative credentials and repositories (copied from ocean-icechunks/icechunks) |
| `publish_viewer.py` | Builds the gridlook browser viewer and uploads it beside a store (adapted from ocean-icechunks/icechunks) |
| `roms_hiig_reanalysis/` | Reanalysis v2.0 store (#11). Start with its [`how_store_created.md`](roms_hiig_reanalysis/how_store_created.md) |

```bash
/srv/conda/bin/python3.12 -m venv ~/venvs/pacioos
~/venvs/pacioos/bin/pip install --no-cache-dir -r stores/requirements.txt
~/venvs/pacioos/bin/python -I stores/smoke_test.py /tmp/pacioos-smoke   # about 1.5 minutes
```

The smoke test reads only the public copies at `https://data.source.coop/ocean-icechunks/pacioos/`,
anonymously. What the file headers showed, and why the code does what it does, is in
[`docs/design/file-headers.md`](../docs/design/file-headers.md).
