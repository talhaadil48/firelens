"""Phase 4–5 pipeline CLI: normalize harvested CSVs, precompute chunks/vectors, write snapshot."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from api.config import ROOT
from harvest.normalize import load_column_maps, normalize_all
from harvest.precompute import build_chunks, build_investigations, build_vectors, write_snapshot


def _default_raw_dir() -> Path:
    latest = ROOT / "raw/latest-harvest.json"
    if latest.exists():
        data = json.loads(latest.read_text(encoding="utf-8"))
        candidate = ROOT / "raw" / data["run_id"]
        if candidate.exists():
            return candidate
    plan_aligned = ROOT / "raw/plan-aligned-20261114"
    if plan_aligned.exists():
        return plan_aligned
    return ROOT / "raw"


def run_pipeline(
    stage: str,
    raw_dir: Path,
    maps_dir: Path,
    snapshots_dir: Path,
    snapshot_id: str,
    live_embeddings: bool = False,
) -> dict:
    """Execute normalize, precompute, snapshot, or all stages."""
    column_maps = load_column_maps(maps_dir)
    rows, frame, stats = normalize_all(raw_dir, maps_dir)
    if stage == "normalize":
        out_dir = snapshots_dir / snapshot_id
        out_dir.mkdir(parents=True, exist_ok=True)
        from harvest.precompute import _parquet_safe_frame

        _parquet_safe_frame(frame).to_parquet(out_dir / "tests.parquet", index=False)
        return {"stage": stage, "stats": stats, "output": str(out_dir / "tests.parquet")}

    investigations = build_investigations(raw_dir, rows, column_maps)
    chunks = build_chunks(raw_dir, investigations)
    if stage == "precompute":
        out_dir = snapshots_dir / snapshot_id
        out_dir.mkdir(parents=True, exist_ok=True)
        vec_meta = build_vectors(chunks, out_dir / "vectors", live_embeddings=live_embeddings)
        return {
            "stage": stage,
            "stats": stats,
            "investigations": len(investigations),
            "chunks": len(chunks),
            "vectors": vec_meta,
        }

    pointer = write_snapshot(
        snapshots_dir=snapshots_dir,
        snapshot_id=snapshot_id,
        rows=rows,
        frame=frame,
        investigations=investigations,
        chunks=chunks,
        normalize_stats=stats,
        live_embeddings=live_embeddings,
    )
    return {
        "stage": stage,
        "stats": stats,
        "pointer": pointer.model_dump(mode="json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["normalize", "precompute", "snapshot", "all"])
    parser.add_argument("--raw-dir", type=Path, default=None)
    parser.add_argument("--maps-dir", type=Path, default=ROOT / "harvest/maps")
    parser.add_argument("--snapshots-dir", type=Path, default=ROOT / "snapshots")
    parser.add_argument(
        "--snapshot-id",
        default=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
    )
    parser.add_argument("--live-embeddings", action="store_true")
    args = parser.parse_args()

    raw_dir = args.raw_dir or _default_raw_dir()
    result = run_pipeline(
        stage=args.stage,
        raw_dir=raw_dir,
        maps_dir=args.maps_dir,
        snapshots_dir=args.snapshots_dir,
        snapshot_id=args.snapshot_id,
        live_embeddings=args.live_embeddings,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
