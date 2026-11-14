# Snapshots

- `sample/`: Phase 2 metadata fixture (mock mode, contract tests). Not a science snapshot.
- `latest.json` + the folder it names: the **committed** snapshot. The API image bakes it
  in and serves it in snapshot mode (DECISIONS 14). `tests/test_committed_snapshot.py`
  fails CI if the pointer names a folder that is not committed.
- Any other `<timestamp>/` folder is a local rebuild and stays git-ignored.

## Rebuild locally

```bash
make harvest     # PSI -> raw/ (cached; only new or changed files are fetched)
make snapshot    # raw/ -> snapshots/<timestamp>/ and moves latest.json to it
```

`make snapshot` moves `latest.json` to your new local folder. Do not commit that pointer
on its own: CI would fail because the folder it names is ignored. Either restore it
(`git checkout snapshots/latest.json`) or commit the new snapshot as below.

## Commit a new snapshot (data freeze)

1. Check `SNAPSHOT.md` in the new folder (counts, documents, reviewed tests).
2. Add `!snapshots/<timestamp>/` to `.gitignore`, removing the previous folder's line
   (and `git rm -r` that folder) so the image carries one snapshot.
3. `git add snapshots/latest.json snapshots/<timestamp>` and commit.
