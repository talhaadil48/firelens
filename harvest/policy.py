"""Select files by manifest category, never by a guessed scientific interpretation."""

import math
import re
from pathlib import PurePosixPath

from harvest.storage import HarvestError, safe_name

DOCUMENT_LIMIT = 20_000_000  # strict decimal 20 MB; equality is excluded
TABLE_LIMIT = 20_000_000
ALLOWED_DOCUMENTS = {"Reports", "Science Documents"}


def category(accession: str, file: dict) -> str:
    for key in ("s3_path", "remote_path", "psi_legacy_s3_path"):
        path = str(file.get(key) or "").replace("\\", "/")
        parts = PurePosixPath(path).parts
        if accession in parts:
            index = parts.index(accession)
            if index + 1 < len(parts):
                return parts[index + 1]
    name = str(file.get("file_name") or "")
    prefix = accession + "_"
    if name.startswith(prefix) and "_" in name[len(prefix) :]:
        return name[len(prefix) :].split("_", 1)[0]
    return "Unknown"


def select_files(accession: str, manifest: dict) -> tuple[list[dict], dict[str, int]]:
    selected, skipped, seen = [], {}, set()

    def skip(reason):
        skipped[reason] = skipped.get(reason, 0) + 1

    for is_table, entries in [
        (True, manifest.get("experimentalTable") or []),
        (False, manifest.get("added") or []),
    ]:
        for original in entries:
            file = dict(original)
            name = file.get("file_name") or ""
            kind = "Experimental table" if is_table else category(accession, file)
            if kind == "Experimental table":
                is_csv = name.lower().endswith(".csv")
                if not is_csv:
                    skip("experimental_non_csv")
                    continue
                role = "table"
            elif kind in ALLOWED_DOCUMENTS:
                role = "document"
            else:
                skip("category:" + kind)
                continue
            identity = (name, file.get("version"), file.get("s3_version_id"))
            if identity in seen:
                skip("duplicate_manifest_entry")
                continue
            seen.add(identity)
            if file.get("restricted") or file.get("visible") is False:
                skip("restricted_or_hidden")
                if role == "table":
                    # Not silently treated as a complete public download.
                    selected.append(
                        {
                            "role": role,
                            "category": kind,
                            "file": file,
                            "policy_error": "Experimental table is restricted/hidden",
                        }
                    )
                continue
            try:
                local = safe_name(name)
                raw_size = file.get("file_size")
                size = float(raw_size) if raw_size is not None else None
                if size is not None and (not math.isfinite(size) or size < 0):
                    raise HarvestError("Invalid advertised file size")
                if size is not None and size >= DOCUMENT_LIMIT:
                    if role == "document":
                        skip("document_at_or_over_20_MB")
                        continue
                    raise HarvestError("Experimental CSV meets/exceeds the table safety limit")
                selected.append({"role": role, "category": kind, "file": file, "local_name": local})
            except HarvestError as exc:
                selected.append(
                    {"role": role, "category": kind, "file": file, "policy_error": str(exc)}
                )
    return selected, skipped


def accession_from(hit: dict) -> str:
    accession = str(hit.get("_source", {}).get("Accession") or "")
    if not re.fullmatch(r"PSI-\d+", accession):
        raise HarvestError("Combustion catalogue record has a missing/invalid accession")
    return accession


def validate_document(content: bytes, name: str) -> None:
    if not content:
        raise HarvestError("Downloaded document is empty")
    if name.lower().endswith(".pdf") and not content.startswith(b"%PDF-"):
        raise HarvestError("Document does not have a PDF signature")
    if name.lower().endswith((".docx", ".xlsx", ".pptx", ".zip")) and not content.startswith(b"PK"):
        raise HarvestError("Document does not have an Office/ZIP signature")
    if not name.lower().endswith((".html", ".htm")) and content.lstrip().lower().startswith(
        (b"<!doctype html", b"<html", b"<error")
    ):
        raise HarvestError("Received an HTML/XML error page instead of a document")
