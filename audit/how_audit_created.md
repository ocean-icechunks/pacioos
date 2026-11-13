# How this audit was created

The audit in this folder was made by a coding agent (Claude Code) working with Eli Holmes on
2026-11-13, following the `archive-to-cloud` skill's audit step and the `virtual-icechunk` skill
(both in [ocean-icechunks/ocean-icechunks-skills](https://github.com/ocean-icechunks/ocean-icechunks-skills)),
and modelled on the CEFI audit (`audit/report.md` in noaa-nwfsc/cefi-icechunks).

The scripts here reproduce it as it was run (see "Method" in [`report.md`](report.md)). The
prompt below is for an agent asked to **recreate or redo** it: for a later state of the copies,
for a new dataset, or for the hindcast once it is copied. Paste it into a session started in
this repository.

## Prompt

```text
Audit the PacIOOS NetCDF copies on Source Cooperative before any virtual Icechunk store is
built over them. Use the archive-to-cloud skill (source audit) and the virtual-icechunk skill,
and model the report on the CEFI audit (~/cefi-icechunks/audit/report.md if present; otherwise
the structure described below). Read AGENTS.md, agent/handoff.md and docs/design/ first.

Scope
- Every file under s3://ocean-icechunks/pacioos/<product>/netcdf/ (endpoint
  https://data.source.coop, anonymous): today roms_hiig, roms_hiig_reanalysis (v2.0),
  wrf_hi, ww3_hawaii. Every header; data only where a check needs it.
- Do not read from the PacIOOS server. The only allowed contact is PacIOOS's public ERDDAP:
  the time axis of each dataset (one request each) and a handful of single-point values.
  Space requests seconds apart.
- The goal it serves: one virtual store per product serving THREDDS's "best" series (newest
  run wins at each valid time, lead 0 included), plus an all-runs view later. For every
  problem ask: does it stop files sharing one Zarr array or one time axis, and does it put
  wrong data at a valid time in the best series?

Environment
- Python 3.12 venv from /srv/conda/bin/python3.12 (not /usr/bin/python3.12), pip
  --no-cache-dir, only audit/requirements.txt. Check the memory cap
  (cat /sys/fs/cgroup/memory.max): the hub is shared.
- HDF5 header scans with h5py over HTTPS: at most ~6 processes on a 7.8 GB hub (16 set off
  the OOM killer 61 times), with maxtasksperchild. NetCDF-3 headers are plain byte-range
  reads: threads are fine. Make every scanner resumable (one JSON line per file).

What to check (and how it was done last time)
1. Inventory: every object, path layout, name pattern, year folder vs name date, stray
   objects, one .md5 per .nc.
2. Sidecars: .md5 format and the name inside it; for single-part uploads the S3 ETag IS the
   MD5, so compare them (free verification of stored bytes); list multipart ones.
3. Headers of every file: format from the magic bytes; NetCDF-3 parsed with a small parser of
   our own (begin, vsize, record vs fixed, numrecs, recsize) and the size the header implies
   (truncation); HDF5 via h5py chunk_iter (all chunks allocated, sizes, filters, whether a
   variable's chunks are back to back); dtypes with byte order; attributes; time values
   (all for HDF5 and fixed-dimension files; first/second/last plus a sample for record files);
   lat/lon/depth/mask hashes.
4. Consistency per product: layout signature segments over time (format eras), variable
   sets, attribute changes, time units, run start hours, steps per run, step regularity,
   first step vs name date, duplicate starts, gaps, files written long after their date
   (history), grids across files and products.
5. Coverage: rebuild the best time axis from the run starts and ends and compare it with
   ERDDAP's over the common span.
6. Values: the first and last top-level plane of one variable per file (~4 GB): all fill,
   constant, out of range, fill count vs land mask, and byte-identical planes shared between
   files (repeated runs).
7. Follow up every surprise with a repro script under audit/repro/: classify repeated runs
   by data shift vs label shift (relabelled copy vs fallback tail); a time-alignment test
   (RMS against neighbours at matched valid times, shifted -48..+48 h, skipping spin-up) for
   files whose labels look off; check tie-breaking and cold starts against single ERDDAP
   values; count best-series steps taken from problem runs.
8. Chunking options for the stores: which contiguous byte ranges exist (depth planes, whole
   columns, multi-step chunks) and whether multi-step chunks survive the best series (test
   every chunk length on the actual run assignment).

Outputs
- audit/report.md: summary, status table per product, problems P1.. with evidence, why it
  matters and the repro script, smaller inconsistencies, checked and found consistent,
  method with timings, limitations, appendix of affected files.
- audit/report-pacioos.md (plus a Claude Doc for the PacIOOS team if asked): plain language,
  what was found, every chunk option with the cost of a map, a profile and a point time
  series, the recommendation and why, whether rewriting the NetCDFs would be worth it, a
  better NetCDF layout for future files, questions for PacIOOS.
- Commit the scripts, findings.csv, products.csv, runs.csv and the reports; keep large scan
  outputs (headers.jsonl, parquet files, ERDDAP CSVs) out of git.
- Verify by running: rerun the cheap steps in a clean venv from audit/requirements.txt and
  check findings.csv comes out identical. Report what the runs printed.
- Correct earlier notes that the files contradict (with date and evidence), and comment on
  the store issues with what changes their decisions. Never edit or move a copy: they are
  write-once.
```

## What the first run found, for comparison

See [`report.md`](report.md). In short: the copies are complete and their best time axes equal
ERDDAP's. WRF changes format on 2017-08-16. 71 WRF runs (2010–13) are relabelled copies. 8 WW3
files from 2020 look a day early. 81 WW3 runs are cold starts. Ties between runs go to the later
file name. A redo that finds something different should say what changed.
