"""Data pipeline entry point: normalize (check maps) -> snapshot (precompute + write)."""

import argparse
from collections import Counter
from pathlib import Path


def normalize(raw: Path) -> None:
    from harvest.normalize import normalize_all
    from harvest.validation import validate_tests

    results = normalize_all(raw)
    rows = [row for result in results for row in result.rows]
    validate_tests(rows)
    for result in results:
        filled = Counter(
            name
            for row in result.rows
            for name in ("o2_fraction", "pressure_kpa", "flow_cm_s")
            if getattr(row, name) is not None
        )
        print(
            f"{result.accession} {result.file}: {len(result.rows)} tests, "
            f"{result.blank_rows} blank rows skipped, filled {dict(filled)}"
        )
    print(f"{len(rows)} tests pass Pydantic and Pandera validation.")


def snapshot(raw: Path, out: Path) -> None:
    from harvest.snapshot import build

    folder = build(raw, out)
    print(f"Snapshot written: {folder}")
    print((folder / "SNAPSHOT.md").read_text(encoding="utf-8").split("## Normalized")[0])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["normalize", "precompute", "snapshot"])
    parser.add_argument("--raw", type=Path, default=Path("raw"))
    parser.add_argument("--out", type=Path, default=Path("snapshots"))
    args = parser.parse_args()
    if args.stage == "normalize":
        normalize(args.raw)
    else:  # precompute runs inside the snapshot build; both write a new snapshot
        snapshot(args.raw, args.out)


if __name__ == "__main__":
    main()
