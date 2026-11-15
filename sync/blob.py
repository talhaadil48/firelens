"""Minimal Azure Blob access for the sync job, over plain HTTPS with httpx.

Reads are anonymous (the snapshots container is public-read, like the API's reads). Writes
use a bearer token: the job's managed identity inside Container Apps, or a token from
``az account get-access-token --resource https://storage.azure.com/`` for a manual run.
"""

from __future__ import annotations

import os
from typing import Protocol

import httpx

STORAGE_RESOURCE = "https://storage.azure.com/"
BLOB_API_VERSION = "2023-11-03"

CONTENT_TYPES = {
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".parquet": "application/octet-stream",
    ".md": "text/markdown; charset=utf-8",
}


def content_type_for(path: str) -> str:
    for suffix, kind in CONTENT_TYPES.items():
        if path.endswith(suffix):
            return kind
    return "application/octet-stream"


class BlobReader(Protocol):
    def get(self, path: str) -> bytes | None: ...


class BlobWriter(Protocol):
    def put(self, path: str, data: bytes, *, cache_control: str | None = None) -> None: ...


class HttpBlobReader:
    """Anonymous GETs against a public container. Returns None on 404."""

    def __init__(
        self, account_url: str, container: str, transport: httpx.BaseTransport | None = None
    ):
        self.base = f"{account_url.rstrip('/')}/{container.strip('/')}"
        self.http = httpx.Client(timeout=60.0, follow_redirects=True, transport=transport)

    def get(self, path: str) -> bytes | None:
        response = self.http.get(f"{self.base}/{path.lstrip('/')}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.content


def managed_identity_token(transport: httpx.BaseTransport | None = None) -> str:
    """Token for Azure Storage from the Container Apps managed identity endpoint."""
    endpoint = os.environ["IDENTITY_ENDPOINT"]
    header = os.environ["IDENTITY_HEADER"]
    with httpx.Client(timeout=30.0, transport=transport) as client:
        response = client.get(
            endpoint,
            params={"resource": STORAGE_RESOURCE, "api-version": "2019-08-01"},
            headers={"X-IDENTITY-HEADER": header},
        )
        response.raise_for_status()
        return str(response.json()["access_token"])


def token_from_environment() -> str | None:
    """Managed identity when running in Azure, else AZURE_STORAGE_BEARER_TOKEN, else None."""
    if os.environ.get("IDENTITY_ENDPOINT") and os.environ.get("IDENTITY_HEADER"):
        return managed_identity_token()
    token = os.environ.get("AZURE_STORAGE_BEARER_TOKEN", "").strip()
    return token or None


class HttpBlobWriter:
    """Block-blob PUTs with a bearer token. Never deletes anything."""

    def __init__(
        self,
        account_url: str,
        container: str,
        token: str,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base = f"{account_url.rstrip('/')}/{container.strip('/')}"
        self.token = token
        self.http = httpx.Client(timeout=300.0, transport=transport)

    def put(self, path: str, data: bytes, *, cache_control: str | None = None) -> None:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "x-ms-version": BLOB_API_VERSION,
            "x-ms-blob-type": "BlockBlob",
            "x-ms-blob-content-type": content_type_for(path),
            "Content-Type": content_type_for(path),
        }
        if cache_control:
            headers["x-ms-blob-cache-control"] = cache_control
        response = self.http.put(f"{self.base}/{path.lstrip('/')}", content=data, headers=headers)
        response.raise_for_status()
