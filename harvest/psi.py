"""PSI (psi.nasa.gov) access shared by the spike, fixtures and the harvester.

Signed download URLs are temporary credentials: they are consumed immediately and are
NEVER written to disk, logs or exception messages.
"""

import asyncio
import csv
import hashlib
import io
import json
import time
from urllib.parse import urlsplit

import httpx

BASE_URL = "https://psi.nasa.gov"
USER_AGENT = "FireLens/0.2 NASA-Space-Apps-harvester"
CATALOGUE_PATH = "/geode-py/ws/repo/search"
CATALOGUE_PARAMS = {"term": "combustion", "source": "psi", "type": "investigation", "size": 100}
RETRY_STATUS = (429, 500, 502, 503, 504)


def manifest_url(accession: str) -> str:
    return f"{BASE_URL}/geode-py/ws/repo/investigations/{accession}"


def page_url(accession: str) -> str:
    """Human-facing PSI page; what citations link to."""
    return f"{BASE_URL}/physci/repo/data/investigations/{accession}"


def download_resolver_url(accession: str) -> str:
    return f"{BASE_URL}/geode-py/ws/studies/{accession}/download"


def read_signed_url(text: str) -> str:
    """PSI returns text, sometimes quoted; preserve the complete query string."""
    value = text.strip()
    if value.startswith('"'):
        value = json.loads(value)
    elif value.startswith("'") and value.endswith("'"):
        value = value[1:-1]
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not (host == "psi.nasa.gov" or host.endswith(".amazonaws.com")):
        raise ValueError("PSI resolver did not return an expected HTTPS download URL")
    return value


def decode_csv(content: bytes) -> tuple[str, str]:
    """Return (text, encoding). FLEX is a legacy Windows export (e.g. en dash byte 0x96)."""
    try:
        return content.decode("utf-8-sig"), "utf-8-sig"
    except UnicodeDecodeError:
        return content.decode("cp1252"), "cp1252"


def csv_summary(content: bytes) -> dict:
    text, encoding = decode_csv(content)
    if text.lstrip().lower().startswith(("<!doctype", "<html", "<?xml", "<error")):
        raise ValueError("Expected CSV, received HTML/XML")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or len(rows[0]) < 2:
        raise ValueError("Expected a nonempty table with multiple columns")
    return {
        "headers": rows[0],
        "physical_data_rows": max(0, len(rows) - 1),
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
        "encoding": encoding,
    }


def fetch(client: httpx.Client, url: str, *, params: dict | None = None) -> httpx.Response:
    """Retry temporary failures; never include URLs containing signatures in errors."""
    for attempt in range(3):
        try:
            response = client.get(url, params=params)
            if response.status_code in RETRY_STATUS and attempt < 2:
                time.sleep(2**attempt)
                continue
            response.raise_for_status()
            return response
        except httpx.TransportError:
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("Retry loop exhausted")


async def afetch(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict | None = None,
    attempts: int = 4,
) -> httpx.Response:
    """Async variant with exponential backoff (1, 2, 4 s)."""
    for attempt in range(attempts):
        last = attempt == attempts - 1
        try:
            response = await client.get(url, params=params)
            if response.status_code in RETRY_STATUS and not last:
                await asyncio.sleep(2**attempt)
                continue
            response.raise_for_status()
            return response
        except httpx.TransportError:
            if last:
                raise
            await asyncio.sleep(2**attempt)
    raise RuntimeError("Retry loop exhausted")


async def download_table(client: httpx.AsyncClient, accession: str, file_name: str) -> bytes:
    """Resolve a signed link for one experimental table and fetch it immediately."""
    resolved = await afetch(
        client,
        download_resolver_url(accession),
        params={"file": file_name, "redirect": "false"},
    )
    signed_url = read_signed_url(resolved.text)
    return (await afetch(client, signed_url)).content


def async_client(timeout: float = 90) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    )
