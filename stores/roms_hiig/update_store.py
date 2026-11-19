"""Daily update of the ROMS Hawaiʻi forecast best-series store (issue #4).

Each run does: read the state → diff it against what should be there → do the missing work.

  1. scan     the header of every run on Source Cooperative not yet in <workdir>/scan.jsonl
              (build_store.scan: anonymous, read-only)
  2. check    every file's structure (build_store.check); stops on anything unexpected
  3. plan     the best series from all checked runs (forecast_store.build_dataset)
  4. diff, update, verify: ../best_series_update.py, shared with the other forecast stores

Nothing to do → nothing is committed. It stops rather than shorten the axis or uncover a
covered step. See ../best_series_update.py for what each step does.

  python update_store.py --dest scratch --dry-run    # what would change, writes nothing
  python update_store.py --dest scratch
  python update_store.py --dest production

Needs the venv from requirements.txt and, to write, Source Cooperative credentials.
An existing ~/.source-coop/pacioos.key is auto-selected (boto3 required); otherwise
use source-coop login --duration 1d --port 8400. SOURCE_COOP_AUTH=api-key|cli selects
explicitly; SOURCE_COOP_API_KEY_FILE overrides the key path.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import best_series_update as bsu  # noqa: E402
import build_store as bs  # noqa: E402
import forecast_store as fs  # noqa: E402

Stop = bsu.Stop


def update(repo, storage, planned, dry_run: bool = False) -> dict | None:
    """Diff the store against `planned` and apply the difference. Returns the change summary."""
    return bsu.update(repo, storage, planned, fs.open_store, dry_run=dry_run)


if __name__ == '__main__':
    bsu.main(__doc__.split('\n\n')[0], bs, fs.open_store, default_procs=4)
