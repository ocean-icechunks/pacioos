"""Scan and build the HDF5-era WRF best series (issue #12)."""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import multiprocessing as mp
import re
import ssl
import sys
from time import sleep
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

from aiohttp import ClientError
import certifi
import icechunk
import numpy as np
from obstore.store import S3Store
import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pacioos_virtual as pv

BUCKET = "ocean-icechunks"
PUBLIC = "https://data.source.coop"
SOURCE = "pacioos/wrf_hi/netcdf/"
DESTINATIONS = {
    "scratch": "test-repo/pacioos/wrf_hi/icechunk-build",
    "production": "pacioos/wrf_hi/icechunk",
}
TITLE = "WRF Regional Atmospheric Model: Main Hawaiian Islands Forecast"
METADATA_FILE = Path(__file__).with_name("erddap_metadata.json")
GLOBAL_DISPLAY_ATTRS = {
    "_CoordSysBuilder", "cdm_data_type", "defaultGraphQuery", "drawLandMask",
    "sourceUrl", "location", "testOutOfDate", "time_coverage_start", "time_coverage_end",
}
DESCRIPTIVE_ATTRS = ("long_name", "standard_name", "units")
ERDDAP = "https://pae-paha.pacioos.hawaii.edu/erddap"
FIRST_RUN = "20170816"
FILENAME = re.compile(r"wrf_hi_(\d{8})\.nc")
SCIENCE = ("Tair", "Pair", "rain", "Uwind", "Vwind", "lwrad_down", "swrad", "Qair")
CHUNK = (1, 138, 213)
HOURS_PER_YEAR = 8760
DUPLICATE_FILE = "wrf_hi_20190429.nc"
DUPLICATE_TIME = pd.Timestamp("2019-05-06T00:00")
READ_ATTEMPTS = 3


def list_runs() -> list[str]:
    store = S3Store(BUCKET, endpoint=PUBLIC, region="us-east-1", skip_signature=True)
    keys = []
    for batch in store.list(prefix=SOURCE):
        for item in batch:
            key = item["path"]
            match = FILENAME.fullmatch(key.rsplit("/", 1)[-1])
            if match and match[1] >= FIRST_RUN:
                keys.append(key.removeprefix("pacioos/"))
    keys.sort(key=lambda key: key.rsplit("/", 1)[-1])
    if not keys or keys[0].rsplit("/", 1)[-1] != f"wrf_hi_{FIRST_RUN}.nc":
        raise ValueError("Source listing does not include the first Era 2 run")
    if len({key.rsplit("/", 1)[-1] for key in keys}) != len(keys):
        raise ValueError("Source listing contains duplicate filenames")
    return keys


def grid_signature(coords: dict) -> dict:
    return {
        name: [str(values.dtype), list(values.shape), hashlib.sha256(values.tobytes()).hexdigest()]
        for name, values in sorted(coords.items())
    }


def scan_one(key: str, cache: Path) -> None:
    path = cache / (key.rsplit("/", 1)[-1] + ".json")
    if path.exists():
        return
    for attempt in range(READ_ATTEMPTS):
        try:
            source = pv.scan_h5(key)
            break
        except (OSError, ClientError) as error:
            if attempt == READ_ATTEMPTS - 1:
                raise RuntimeError(f"Could not read WRF header: {key}") from error
            sleep(2 ** attempt)
    times = source["time"]
    repeated = times[times.duplicated()]
    expected = [DUPLICATE_TIME] if key.endswith("/" + DUPLICATE_FILE) else []
    if list(repeated) != expected or not times.is_monotonic_increasing:
        raise ValueError(f"{key}: unexpected time order or repeated hours")
    unique = times.drop_duplicates()
    if (unique != unique.floor("h")).any() or not (np.diff(unique) == np.timedelta64(1, "h")).all():
        raise ValueError(f"{key}: expected consecutive whole hours")
    variables = source["vars"]
    fields = {name for name, record in variables.items() if len(record["shape"]) >= 3}
    if fields != set(SCIENCE):
        raise ValueError(f"{key}: unexpected forecast variables {sorted(fields)}")
    offsets = {}
    plane_bytes = int(np.prod(CHUNK) * np.dtype("<f4").itemsize)
    for name in SCIENCE:
        record = variables[name]
        if (record["shape"] != (len(times), *CHUNK[1:]) or record["chunk"] != CHUNK
                or record["dtype"] != "<f4" or "_FillValue" in record["attrs"]
                or len(record["offsets"]) != len(times) or not (record["nbytes"] == plane_bytes).all()):
            raise ValueError(f"{key}: incompatible encoding for {name}")
        offsets[name] = record["offsets"].tolist()
    rec = {"key": key, "time": [t.isoformat() for t in times],
           "grid": grid_signature(source["coords"]), "offsets": offsets}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec))
    tmp.replace(path)


def scan_cached(task: tuple[str, Path]) -> None:
    scan_one(*task)


def scan(keys: list[str], cache: Path, workers: int) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    print(f"Scanning {len(keys)} Era 2 files with {workers} workers", flush=True)
    with mp.get_context("spawn").Pool(workers, maxtasksperchild=200) as pool:
        for count, _ in enumerate(pool.imap_unordered(scan_cached, ((key, cache) for key in keys)), 1):
            if count % 100 == 0 or count == len(keys):
                print(f"{count}/{len(keys)} headers checked", flush=True)


def load_scans(keys: list[str], cache: Path, grid: dict) -> list[dict]:
    scans = []
    plane_bytes = int(np.prod(CHUNK) * np.dtype("<f4").itemsize)
    for key in keys:
        path = cache / (key.rsplit("/", 1)[-1] + ".json")
        record = json.loads(path.read_text())
        if record["key"] != key or record["grid"] != grid:
            raise ValueError(f"{key}: cached key or grid differs")
        times = pd.DatetimeIndex(record["time"])
        variables = {
            name: {"shape": (len(times), *CHUNK[1:]), "dtype": "<f4",
                   "offsets": np.asarray(record["offsets"][name], dtype="uint64"),
                   "nbytes": np.full(len(times), plane_bytes, dtype="uint64")}
            for name in SCIENCE
        }
        scans.append({"key": key, "format": "hdf5", "time": times, "vars": variables})
    return scans


def best_series(scans: list[dict]) -> pd.DataFrame:
    # The two duplicate records were compared across all eight fields and are equal.
    # Keep the original index of the last record after deduplicating.
    unique = []
    original_indices = []
    for source in scans:
        keep = np.flatnonzero(~source["time"].duplicated(keep="last"))
        unique.append({"time": source["time"][keep]})
        original_indices.append(keep)
    best = pv.best_assignment(unique, "1h")
    best = best.loc[best["run"] >= 0].copy()
    best["lead"] = [original_indices[run][lead] for run, lead in best.itertuples(index=False, name=None)]
    return best


def erddap_metadata() -> tuple[dict, dict]:
    snapshot = json.loads(METADATA_FILE.read_text())
    attrs: dict[str, dict] = {}
    for row_type, name, key, dtype, value in snapshot["rows"]:
        if row_type != "attribute":
            continue
        if dtype in {"double", "float", "Float64", "Float32"}:
            value = float(value)
        attrs.setdefault(name, {})[key] = value
    global_attrs = {key: value for key, value in attrs["NC_GLOBAL"].items()
                    if key not in GLOBAL_DISPLAY_ATTRS}
    global_attrs.update({
        "title": TITLE,
        "source_files": f"{PUBLIC}/{BUCKET}/{SOURCE}",
        "metadata_source": (
            f"PacIOOS ERDDAP wrf_hi ({ERDDAP}/info/wrf_hi/index.html), "
            f"saved {snapshot['fetched']} in stores/wrf_hi/erddap_metadata.json."
        ),
    })
    variables = {name: {key: attrs[name][key] for key in DESCRIPTIVE_ATTRS if key in attrs[name]}
                 for name in SCIENCE}
    for name, source in (("lat", "latitude"), ("lon", "longitude"), ("time", "time")):
        keys = ("axis", "long_name", "standard_name", "units") if name != "time" else (
            "axis", "long_name", "standard_name",
        )
        variables[name] = {key: attrs[source][key] for key in keys if key in attrs[source]}
    return global_attrs, variables


def build_dataset(scans: list[dict], reference: dict, best: pd.DataFrame) -> xr.Dataset:
    attrs, var_attrs = erddap_metadata()
    variables = {
        name: pv.manifest_variable(name, scans, best, ("time", "lat", "lon"), var_attrs[name])
        for name in SCIENCE
    }
    starts = pd.DatetimeIndex([scans[run]["time"][0] for run in best["run"]])
    dataset = xr.Dataset(variables, coords={
        "time": ("time", best.index, var_attrs["time"]),
        "lat": ("lat", reference["coords"]["lat"], var_attrs["lat"]),
        "lon": ("lon", reference["coords"]["lon"], var_attrs["lon"]),
        "forecast_reference_time": ("time", starts, {"standard_name": "forecast_reference_time"}),
        "forecast_period": ("time", (best.index - starts) / pd.Timedelta(hours=1),
                            {"standard_name": "forecast_period", "units": "hours"}),
    }, attrs={
        **attrs,
        "time_coverage_start": best.index[0].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "time_coverage_end": best.index[-1].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "comment": (attrs.get("comment", "") + " Era 2 HDF5 runs only. Each covered hour uses "
                    "the newest available run, with ties going to the later filename.").strip(),
        "forecast_runs": len(scans),
        "run_inventory_sha256": hashlib.sha256(
            "\n".join(source["key"] for source in scans).encode()
        ).hexdigest(),
        "latest_run_start": max(s["time"][0] for s in scans).isoformat(),
    })
    for name in ("time", "forecast_reference_time", "forecast_period"):
        dataset[name].encoding["chunks"] = (len(best),)
    return dataset


def service_account_storage(key_file: Path, role_arn: str, prefix: str) -> icechunk.Storage:
    """Exchange a Source Cooperative service-account key for S3 credentials."""
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    region = "us-west-2"
    sts = boto3.client("sts", endpoint_url=f"{PUBLIC}/.sts", region_name=region,
                       config=Config(signature_version=UNSIGNED))
    credentials = sts.assume_role_with_web_identity(
        RoleArn=role_arn, RoleSessionName="pacioos-wrf",
        WebIdentityToken=key_file.read_text().strip(), DurationSeconds=3600,
    )["Credentials"]
    return icechunk.s3_storage(
        bucket=BUCKET, prefix=prefix, region=region, endpoint_url=PUBLIC,
        force_path_style=True, access_key_id=credentials["AccessKeyId"],
        secret_access_key=credentials["SecretAccessKey"], session_token=credentials["SessionToken"],
    )


def write_store(dataset: xr.Dataset, dest: str, key_file: Path | None, role_arn: str | None) -> None:
    import zarr

    prefix = DESTINATIONS[dest]
    config = pv.repository_config(HOURS_PER_YEAR)
    if key_file is not None and role_arn is not None:
        storage = service_account_storage(key_file, role_arn, prefix)
        if icechunk.Repository.exists(storage):
            repo = icechunk.Repository.open(storage, config=config)
        else:
            repo = icechunk.Repository.create(storage, config=config)
    else:
        from icechunk_utils import open_source_icechunk_repo

        repo, *_ = open_source_icechunk_repo(
            bucket=BUCKET, prefix=prefix, config=config, min_minutes_left=20, verbose=False,
        )
        if repo is None:
            raise SystemExit("Refresh Source Cooperative credentials before writing")
    repo = repo.reopen(authorize_virtual_chunk_access=pv.reader_authorization())
    current = repo.readonly_session("main")
    if asyncio.run(current.store.exists("zarr.json")):
        existing = xr.open_zarr(current.store, consolidated=False, chunks=None)
        if existing.attrs.get("run_inventory_sha256") != dataset.attrs["run_inventory_sha256"]:
            raise SystemExit(f"{prefix} already contains a different run inventory")
        if metadata_matches(existing, dataset):
            print(f"{dest} snapshot {current.snapshot_id} already matches", flush=True)
            return
        session = repo.writable_session("main")
        group = zarr.open_group(session.store, mode="r+")
        # Keep xarray's global coordinate encoding when replacing descriptive metadata.
        group.attrs.put({**dataset.attrs, "coordinates": " ".join(dataset.coords)})
        for name in (*SCIENCE, "time", "lat", "lon"):
            group[name].attrs.update(dataset[name].attrs)
        snapshot = session.commit("Apply PacIOOS ERDDAP metadata to WRF Era 2")
    else:
        repo.save_config()
        session = repo.writable_session("main")
        dataset.vz.to_icechunk(session.store)
        snapshot = session.commit(f"WRF Era 2 best series ({dataset.sizes['time']} hours)")
    print(f"{dest} snapshot {snapshot}", flush=True)


def metadata_matches(actual: xr.Dataset, expected: xr.Dataset) -> bool:
    return actual.attrs == expected.attrs and set(actual.coords) == set(expected.coords) and all(
        all(actual[name].attrs.get(key) == value for key, value in expected[name].attrs.items())
        for name in (*SCIENCE, "time", "lat", "lon")
    )


def erddap_csv(query: str) -> list[list[str]]:
    url = f"{ERDDAP}/griddap/wrf_hi.csv?" + quote(query, safe=",:.()-")
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    with urlopen(url, timeout=120, context=context) as response:
        return list(csv.reader(response.read().decode().splitlines()))


def validate(scans: list[dict], best: pd.DataFrame, expected_dataset: xr.Dataset, dest: str) -> None:
    import netCDF4

    storage = icechunk.http_storage(f"{PUBLIC}/{BUCKET}/{DESTINATIONS[dest]}")
    repo = icechunk.Repository.open(storage, authorize_virtual_chunk_access=pv.reader_authorization())
    dataset = xr.open_zarr(repo.readonly_session("main").store, consolidated=False, chunks=None)
    pd.testing.assert_index_equal(pd.DatetimeIndex(dataset.time.values).as_unit("ns"),
                                  best.index.as_unit("ns"), check_names=False)
    assert set(dataset.data_vars) == set(SCIENCE)
    assert metadata_matches(dataset, expected_dataset), "Published ERDDAP metadata differs"
    rows = erddap_csv("time")
    axis = pd.to_datetime([row[0] for row in rows[2:]], utc=True).tz_localize(None).as_unit("ns")
    expected = axis[(axis >= best.index[0]) & (axis <= best.index[-1])]
    pd.testing.assert_index_equal(expected, best.index.as_unit("ns"), check_names=False)
    # Avoid the archive tail, where newer uncopied runs can change historical winners.
    for pos in np.linspace(0, len(best) - 1, 5, dtype=int)[:-1]:
        run, lead = best.iloc[pos]
        with netCDF4.Dataset(pv.URL_PREFIX + scans[run]["key"] + "#mode=bytes") as source:
            np.testing.assert_array_equal(dataset.Tair.isel(time=pos).values, source["Tair"][lead])
        iy, ix = len(dataset.lat) // 2, len(dataset.lon) // 2
        lat, lon = float(dataset.lat[iy]), float(dataset.lon[ix])
        timestamp = best.index[pos].isoformat() + "Z"
        rows = erddap_csv(f"Tair[({timestamp})][({lat})][({lon})]")
        np.testing.assert_allclose(float(dataset.Tair[pos, iy, ix]), float(rows[2][-1]), rtol=1e-6)
    print(f"Validated {len(best)} hours against ERDDAP and four planes and points", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("scan", "check", "write", "validate"))
    parser.add_argument("workdir", type=Path)
    parser.add_argument("--dest", choices=DESTINATIONS, default="scratch")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--key-file", type=Path, help="Source Cooperative service-account key file for write")
    parser.add_argument("--role-arn", help="Source Cooperative service-account FullAccess role for write")
    args = parser.parse_args()
    if (args.key_file is None) != (args.role_arn is None):
        parser.error("--key-file and --role-arn must be supplied together")
    keys = list_runs()
    if args.action == "scan":
        scan(keys, args.workdir, args.workers)
        return
    reference = pv.scan_h5(keys[-1])
    scans = load_scans(keys, args.workdir, grid_signature(reference["coords"]))
    best = best_series(scans)
    print(f"{len(keys)} compatible runs, {len(best)} covered hours: {best.index[0]} to {best.index[-1]}",
          flush=True)
    if args.action == "write":
        write_store(build_dataset(scans, reference, best), args.dest, args.key_file, args.role_arn)
    elif args.action == "validate":
        validate(scans, best, build_dataset(scans, reference, best), args.dest)


if __name__ == "__main__":
    main()
