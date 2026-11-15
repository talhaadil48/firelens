"""FireLens sync job (build step 12.1). Usually run by the Container Apps Job `firelens-sync`.

    python -m sync                 # decide, build if needed, validate, publish
    python -m sync --force         # rebuild and publish even if nothing changed (keeps validation)
    python -m sync --dry-run       # build and validate only; writes nothing to Blob

Prints one JSON line with the result. Exit code 0 for published / no_change / dry_run.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from sync.blob import HttpBlobReader, HttpBlobWriter, token_from_environment
from sync.job import SyncResult, SyncSettings, default_build, default_catalogue, run_sync


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--work-dir", type=Path, default=Path("/tmp/firelens-sync"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    account_url = os.environ.get("AZURE_STORAGE_ACCOUNT_URL", "").strip()
    container = os.environ.get("AZURE_STORAGE_CONTAINER", "snapshots").strip() or "snapshots"
    if not account_url:
        print(
            SyncResult(status="refused", detail="AZURE_STORAGE_ACCOUNT_URL is not set.").to_json()
        )
        return 1

    settings = SyncSettings(work_dir=args.work_dir, force=args.force, dry_run=args.dry_run)
    token = None if args.dry_run else token_from_environment()
    writer = HttpBlobWriter(account_url, container, token) if token else None
    try:
        result = run_sync(
            settings,
            reader=HttpBlobReader(account_url, container),
            writer=writer,
            catalogue=default_catalogue(),
            build=default_build(settings),
        )
    except Exception as exc:  # a crash must still leave one readable line in the job log
        result = SyncResult(status="refused", detail=f"{type(exc).__name__}: {exc}"[:500])
    print(result.to_json(), flush=True)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
