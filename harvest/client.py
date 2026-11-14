"""Bounded NASA downloads. Signed URLs live only in memory, never in errors/cache keys."""

import json
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from harvest.spike import BASE_URL, USER_AGENT, read_signed_url
from harvest.storage import Cache, HarvestError, Receipt, TooLarge, atomic_bytes

RETRY_STATUS = {408, 429, 500, 502, 503, 504}


def public_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise HarvestError("Source must be an HTTPS public URL without user credentials")
    host = parsed.hostname or ""
    if not (
        host == "nasa.gov"
        or host.endswith(".nasa.gov")
        or host == "spaceappschallenge.org"
        or host.endswith(".spaceappschallenge.org")
    ):
        raise HarvestError("Source host is not an allowed NASA/challenge host")
    if any(
        s in parsed.query.lower()
        for s in ["signature=", "token=", "credential=", "awsaccesskeyid="]
    ):
        raise HarvestError("Temporary credentials cannot be stored as source URLs")
    return url


class SourceClient:
    def __init__(
        self,
        cache: Cache,
        *,
        offline: bool = False,
        refresh: bool = False,
        timeout: float = 40,
        attempts: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.cache, self.offline, self.refresh = cache, offline, refresh
        self.attempts, self.sleep = attempts, sleep
        self.http = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
            headers={"User-Agent": USER_AGENT},
            limits=httpx.Limits(max_connections=4),
        )

    def close(self) -> None:
        self.http.close()

    def _read(self, url: str, limit: int) -> tuple[bytes, str, int]:
        for attempt in range(1, self.attempts + 1):
            try:
                with self.http.stream("GET", url) as response:
                    status = response.status_code
                    if status in RETRY_STATUS and attempt < self.attempts:
                        # Respect a bounded Retry-After without allowing unbounded sleeps.
                        try:
                            pause = float(response.headers.get("retry-after", 2 ** (attempt - 1)))
                        except ValueError:
                            pause = 2 ** (attempt - 1)
                        self.sleep(min(10, max(0, pause)))
                        continue
                    if status >= 400:
                        raise HarvestError(f"HTTP {status}; request URL omitted")
                    length = response.headers.get("content-length")
                    if length and length.isdigit() and int(length) >= limit:
                        raise TooLarge("Declared content length meets/exceeds the byte limit")
                    parts, size = [], 0
                    for chunk in response.iter_bytes(64 * 1024):
                        size += len(chunk)
                        if size >= limit:
                            raise TooLarge("Stream meets/exceeds the byte limit")
                        parts.append(chunk)
                    return b"".join(parts), response.headers.get("content-type", ""), attempt
            except httpx.TransportError:
                if attempt == self.attempts:
                    raise HarvestError("Network/timeout failure; request URL omitted") from None
                self.sleep(2 ** (attempt - 1))
        raise HarvestError("Retry limit reached")

    def resource(
        self,
        url: str,
        target: Path,
        *,
        limit: int = 20_000_000,
        validator: Callable[[bytes], object] | None = None,
        json_resource: bool = False,
    ) -> Receipt:
        public_url(url)
        started = time.perf_counter()
        age = None if self.offline else (0 if self.refresh else 6 * 3600)
        receipt = self.cache.restore(
            url, target, max_age=age if json_resource else None, max_bytes=limit
        )
        if receipt:
            if validator:
                validator(target.read_bytes())
            receipt.seconds = round(time.perf_counter() - started, 3)
            return receipt
        if self.offline:
            raise HarvestError("No verified cache entry available in offline mode")
        content, mime, attempts = self._read(url, limit)
        if validator:
            validator(content)
        receipt = self.cache.save(url, content, content_type=mime)
        atomic_bytes(target, content)
        receipt.attempts, receipt.seconds = attempts, round(time.perf_counter() - started, 3)
        return receipt

    def psi_file(
        self,
        accession: str,
        file: dict,
        target: Path,
        *,
        study_version: str,
        limit: int,
        validator: Callable[[bytes], object] | None = None,
    ) -> Receipt:
        started = time.perf_counter()
        name = file["file_name"]
        # The key identifies immutable source versions, never a signed S3 URL.
        identity = json.dumps(
            [
                accession,
                study_version,
                name,
                file.get("version"),
                file.get("s3_version_id"),
                file.get("file_size"),
            ]
        )
        receipt = self.cache.restore("psi-file:" + identity, target, max_bytes=limit)
        if receipt:
            if validator:
                validator(target.read_bytes())
            receipt.seconds = round(time.perf_counter() - started, 3)
            return receipt
        if self.offline:
            raise HarvestError("No verified file cache entry available in offline mode")
        endpoint = BASE_URL + f"/geode-py/ws/studies/{accession}/download"
        params = {"file": name, "redirect": "false", "studyVersion": study_version}
        if file.get("version") is not None:
            params["version"] = str(file["version"])
        request_url = str(httpx.URL(endpoint, params=params))
        for cycle in range(2):
            try:
                resolved, _, resolution_attempts = self._read(request_url, 100_000)
                signed_url = read_signed_url(resolved.decode())
                content, mime, attempts = self._read(signed_url, limit)
                if validator:
                    validator(content)
                receipt = self.cache.save("psi-file:" + identity, content, content_type=mime)
                atomic_bytes(target, content)
                receipt.attempts = attempts + resolution_attempts
                receipt.seconds = round(time.perf_counter() - started, 3)
                return receipt
            except HarvestError as exc:
                if cycle == 0 and (
                    str(exc).startswith("HTTP 403") or str(exc).startswith("HTTP 401")
                ):
                    continue  # Resolve a NEW signed URL immediately after expiry.
                raise
            except (ValueError, UnicodeError):
                raise HarvestError("Invalid download response; signed URL omitted") from None
        raise HarvestError("Signed URL resolution failed")
