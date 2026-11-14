"""Content-verified cache and atomic, cross-platform raw-file storage."""

import hashlib
import json
import re
import shutil
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


class HarvestError(Exception):
    """A safe diagnostic: messages must never contain signed request URLs."""


class TooLarge(HarvestError):
    pass


@dataclass
class Receipt:
    sha256: str
    bytes: int
    retrieved_at: str
    content_type: str
    cached: bool
    attempts: int = 0
    seconds: float = 0


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".part")
    try:
        temporary.write_bytes(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, value: object) -> None:
    atomic_bytes(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def safe_name(name: str) -> str:
    if not name or name in {".", ".."} or "/" in name or "\\" in name or "\x00" in name:
        raise HarvestError("Unsafe source filename")
    cleaned = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name).rstrip(". ")
    # Leave room for Windows' project/run/category directory prefixes.
    if cleaned != name or len(cleaned) > 100:
        suffix = Path(cleaned).suffix[:12]
        stem = Path(cleaned).stem[:75]
        cleaned = stem + "-" + hashlib.sha256(name.encode()).hexdigest()[:10] + suffix
    if cleaned.split(".")[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *{f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)},
    }:
        cleaned = "_" + cleaned
    return cleaned


class Cache:
    def __init__(self, root: Path):
        self.root = root

    def paths(self, key: str) -> tuple[Path, Path]:
        folder = self.root / hashlib.sha256(key.encode()).hexdigest()
        return folder / "content", folder / "receipt.json"

    def restore(
        self, key: str, target: Path, *, max_age: float | None = None, max_bytes: int | None = None
    ) -> Receipt | None:
        content, metadata = self.paths(key)
        try:
            data = json.loads(metadata.read_text())
            if max_age is not None and time.time() - metadata.stat().st_mtime > max_age:
                return None
            size = content.stat().st_size
            if size != data["bytes"] or digest(content) != data["sha256"]:
                return None
            if max_bytes is not None and size >= max_bytes:
                raise TooLarge("Cached file exceeds the configured byte limit")
            target.parent.mkdir(parents=True, exist_ok=True)
            # Copy, never hardlink: later refreshes cannot mutate prior runs.
            shutil.copyfile(content, target)
            return Receipt(**data, cached=True)
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def save(self, key: str, content: bytes, *, content_type: str) -> Receipt:
        blob, metadata = self.paths(key)
        receipt = Receipt(
            sha256=hashlib.sha256(content).hexdigest(),
            bytes=len(content),
            retrieved_at=datetime.now(UTC).isoformat(),
            content_type=content_type,
            cached=False,
        )
        atomic_bytes(blob, content)
        data = asdict(receipt)
        for field in ["cached", "attempts", "seconds"]:
            data.pop(field)
        write_json(metadata, data)
        return receipt
