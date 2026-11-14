"""Verify a Phase 3 run's original files against recorded SHA-256 hashes, offline."""

import argparse
import json
from pathlib import Path

from harvest.storage import HarvestError, digest


def verify(folder: Path) -> dict:
    report = json.loads((folder / "report.json").read_text())
    failures, checked = [], []

    def check(relative: str, receipt: dict):
        path = (folder / relative).resolve()
        if not path.is_relative_to(folder.resolve()):
            failures.append("Unsafe path in report")
            return
        if not path.is_file():
            failures.append("Missing file: " + relative)
        elif path.stat().st_size != receipt["bytes"] or digest(path) != receipt["sha256"]:
            failures.append("Checksum/size mismatch: " + relative)
        else:
            checked.append(relative)

    for page in report.get("catalogue", {}).get("pages", []):
        check("catalogue/" + page["file"], page["receipt"])
    for investigation in report["investigations"]:
        accession = investigation["accession"]
        if investigation.get("manifest"):
            check(accession + "/manifest.json", investigation["manifest"])
        for file in investigation["files"]:
            if file["status"] == "success":
                check(file["path"], file["receipt"])
    for context in report["context"]:
        if context["status"] != "success":
            continue
        check("context/" + context["id"] + ".html", context["receipt"])
        if context.get("text_integrity"):
            check("context/" + context["text_file"], context["text_integrity"])
        text = folder / "context" / context["text_file"]
        if not text.is_file() or "Source URL: " + context["url"] not in text.read_text():
            failures.append("Missing context text or source URL: " + context["id"])
        if context.get("pdf"):
            check("context/" + context["pdf"]["file"], context["pdf"]["receipt"])
    complete = report["status"] == "complete"
    return {
        "run_id": report["run_id"],
        "success": not failures and complete,
        "integrity_ok": not failures,
        "harvest_complete": complete,
        "verified_files": len(checked),
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="A dated raw run folder containing report.json")
    args = parser.parse_args()
    try:
        result = verify(args.folder)
    except (OSError, ValueError, KeyError, HarvestError):
        parser.exit(1, "Cannot read a valid harvest report from that folder.\n")
    print(json.dumps(result, indent=2))
    if not result["success"]:
        parser.exit(1, "Raw-file verification or harvest completeness check failed.\n")


if __name__ == "__main__":
    main()
