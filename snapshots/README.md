# Snapshots

Only `sample/` is committed. Real timestamped snapshots and pointers are ignored by Git.
`sample/` is a Phase 2 metadata fixture, not a science-validation snapshot.

## Production Snapshot Layout (Phases 5–6 & 12)

Each snapshot written by Phase 5 (`harvest/pipeline.py`) or Phase 12 (`sync/`) uses a
timestamped directory plus a `latest.json` pointer validated by `api.models.SnapshotPointer`:

```text
snapshots/
  latest.json                  # api.models.SnapshotPointer
  <snapshot_id>/
    tests.parquet              # Validated harvest.validation.TestFrame rows
    investigations.json        # api.models.InvestigationList (or list[Investigation])
    chunks.jsonl               # One api.models.TextChunk JSON object per line
    vectors/                   # Embedding index (LanceDB or FAISS)
    SNAPSHOT.md                # Date, counts, source versions, and caveats
```
