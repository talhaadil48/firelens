"""The committed snapshot pointer must resolve, or the API image fails at startup.

api/Dockerfile bakes snapshots/ into the image and starts in snapshot mode. If someone
commits a latest.json that points at a folder they built locally but did not commit, CI
(a clean checkout) fails here instead of the deployed container crashing.
"""

import json
from pathlib import Path

import pytest

from api.store import SnapshotStore, read_pointer

SNAPSHOTS = Path(__file__).resolve().parents[1] / "snapshots"
REQUIRED = ["snapshot.json", "investigations.json", "tests.parquet", "chunks.jsonl", "SNAPSHOT.md"]


@pytest.mark.skipif(not (SNAPSHOTS / "latest.json").exists(), reason="no snapshot pointer")
def test_latest_pointer_loads():
    folder = SNAPSHOTS / read_pointer(SNAPSHOTS)
    missing = [name for name in REQUIRED if not (folder / name).exists()]
    assert not missing, f"{folder.name} is missing {missing}; commit the folder latest.json names"
    store = SnapshotStore(folder)
    info = json.loads((folder / "snapshot.json").read_text(encoding="utf-8"))
    assert store.snapshot_id == info["snapshot_id"] == folder.name
    assert len(store.investigations) == info["investigation_count"]
    assert len(store.tests) == info["test_count"]
    assert all(t.doi and t.provenance.source_file for t in store.tests)  # rule 2: provenance
