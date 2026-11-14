"""
Copied unchanged from ocean-icechunks/icechunks (icechunk_utils.py, 2026-11-14) so this
repository runs on its own; fix bugs in both places.

Helpers for opening Icechunk repositories on Source Cooperative using
temporary credentials managed by the source-coop CLI.
"""

import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import icechunk


def _default_cli() -> str:
    """Locate the source-coop CLI: $SOURCE_COOP_CLI, then $PATH, then ~/.cargo/bin."""
    return (
        os.environ.get("SOURCE_COOP_CLI")
        or shutil.which("source-coop")
        or str(Path.home() / ".cargo" / "bin" / "source-coop")
    )


def _default_creds_cache() -> str:
    """The CLI's own credential cache, honoring $XDG_CACHE_HOME."""
    if env := os.environ.get("SOURCE_COOP_CREDS_CACHE"):
        return env
    cache_home = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return str(cache_home / "source-coop" / "credentials" / "_default.json")


SOURCE_COOP_CLI = _default_cli()
_DEFAULT_CREDS_CACHE = _default_creds_cache()

_LOGIN_HINT = f"Run: {SOURCE_COOP_CLI} login --duration 1d --port 8400"


def get_source_credentials(creds_cache: str | None = None):
    """
    Refresh and return Source Cooperative temporary credentials.

    Calls the source-coop CLI to ensure the cached token is up to date,
    then reads the credentials from the cache file.

    Parameters
    ----------
    creds_cache
        Path to the CLI's credential cache. Defaults to
        ``$SOURCE_COOP_CREDS_CACHE`` or ``~/.cache/source-coop/credentials/_default.json``.

    Returns
    -------
    source_creds : dict
        Keys: aws_access_key_id, aws_secret_access_key, aws_session_token,
        region_name, endpoint_url.
    expiration : datetime
        Token expiration as a timezone-aware UTC datetime. May be in the past —
        a warning is printed, but it is the caller's decision what to do. Use
        ``open_source_icechunk_repo`` if you want a clean stop instead.
    """
    creds_cache = creds_cache or _DEFAULT_CREDS_CACHE

    try:
        subprocess.run([SOURCE_COOP_CLI, "creds"], check=True, stdout=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"source-coop CLI not found at {SOURCE_COOP_CLI!r}. Install it, put it on "
            f"$PATH, or set $SOURCE_COOP_CLI to its location."
        ) from exc

    path = Path(creds_cache)
    if not path.is_file():
        raise FileNotFoundError(
            f"No Source Cooperative credential cache at {path}. {_LOGIN_HINT}"
        )

    with path.open() as f:
        cached = json.load(f)

    expiration = datetime.fromisoformat(cached["expiration"])
    if expiration <= datetime.now(timezone.utc):
        print(f"Warning: Source credentials expired at {expiration}. {_LOGIN_HINT}")

    source_creds = {
        "aws_access_key_id": cached["access_key_id"],
        "aws_secret_access_key": cached["secret_access_key"],
        "aws_session_token": cached["session_token"],
        "region_name": "us-east-1",
        "endpoint_url": "https://data.source.coop",
    }

    return source_creds, expiration


def open_source_icechunk_repo(
    bucket: str,
    prefix: str,
    config=None,
    min_minutes_left: int = 15,
    create_if_missing: bool = True,
    verbose: bool = True,
    check_expiration: bool = True,
):
    """
    Open or create an Icechunk repo on Source Cooperative.

    Refreshes credentials via the source-coop CLI before opening.

    Parameters
    ----------
    bucket
        Source Cooperative bucket name (e.g. "ocean-icechunks").
    prefix
        Key prefix inside the bucket for the Icechunk repository.
    config
        Optional icechunk.RepositoryConfig (e.g. with VirtualChunkContainers).
    min_minutes_left
        If the token has fewer than this many minutes remaining and
        check_expiration=True, returns (None, None, None, time_left) rather than
        starting work that cannot finish. A full archive rebuild takes hours, so
        the default of 15 minutes is a floor, not a recommendation.
    create_if_missing
        Create the repository if it does not already exist. When False, a missing
        repository raises rather than being created.
    verbose
        Print status messages.
    check_expiration
        Enforce min_minutes_left with a clean stop instead of a cryptic error
        partway through a write.

    Returns
    -------
    repo : icechunk.Repository or None
    storage : icechunk storage object or None
    source_creds : dict or None
    time_left : timedelta
    """
    source_creds, expiration = get_source_credentials()

    now = datetime.now(timezone.utc)
    time_left = expiration - now

    if check_expiration and time_left < timedelta(minutes=min_minutes_left):
        state = "expired" if time_left < timedelta(0) else f"expires in {time_left}"
        print(
            f"Stopping cleanly. Source credentials {state}, which leaves less than the "
            f"{min_minutes_left} minutes required. {_LOGIN_HINT}"
        )
        return None, None, None, time_left

    storage = icechunk.s3_storage(
        bucket=bucket,
        prefix=prefix,
        region=source_creds["region_name"],
        endpoint_url=source_creds["endpoint_url"],
        force_path_style=True,
        access_key_id=source_creds["aws_access_key_id"],
        secret_access_key=source_creds["aws_secret_access_key"],
        session_token=source_creds["aws_session_token"],
    )

    # Ask whether the repo exists rather than calling create() and treating any
    # failure as "it must already be there" — that hid credential, network and
    # config errors behind an "Opened existing" message.
    if icechunk.Repository.exists(storage):
        repo = icechunk.Repository.open(storage, config=config)
        if verbose:
            print("Opened existing Icechunk repo")
    elif create_if_missing:
        repo = icechunk.Repository.create(storage, config)
        if verbose:
            print("Created new Icechunk repo")
    else:
        raise icechunk.RepositoryNotFoundError(
            f"No Icechunk repository at s3://{bucket}/{prefix} and create_if_missing=False"
        )

    if verbose:
        print(f"Time remaining on token: {time_left}")

    return repo, storage, source_creds, time_left


def wait_for_fresh_repo(
    bucket: str,
    prefix: str,
    config=None,
    min_minutes_left: int = 15,
    verbose: bool = True,
):
    """
    Open the Icechunk repo, prompting for a token refresh if needed.

    Loops until the token has at least min_minutes_left remaining, or the
    user chooses to stop. Useful before starting a long write loop; needs an
    interactive session, since it prompts with input().

    Returns
    -------
    repo, storage, source_creds, time_left
        Returns (None, None, None, time_left) if the user stops.
    """
    while True:
        repo, storage, source_creds, time_left = open_source_icechunk_repo(
            bucket=bucket,
            prefix=prefix,
            config=config,
            min_minutes_left=min_minutes_left,
            create_if_missing=True,
            check_expiration=True,
            verbose=False,
        )

        if time_left >= timedelta(minutes=min_minutes_left):
            if verbose:
                print(f"Token okay. Time remaining: {time_left}")
            return repo, storage, source_creds, time_left

        print(
            f"Source credentials expire in about {time_left}. "
            f"Refresh with: {SOURCE_COOP_CLI} login --duration 1d --port 8400"
        )

        try:
            answer = input("Enter y after refreshing the token, or n to stop: ").strip().lower()
        except KeyboardInterrupt:
            print("Input interrupted. Stopping cleanly.")
            return None, None, None, time_left

        if answer == "y":
            continue
        if answer == "n":
            print("Stopping. Resume with start_index set to the last committed file.")
            return None, None, None, time_left

        print("Please enter y or n.")
