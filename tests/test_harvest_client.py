import json

import httpx
import pytest

from harvest.client import SourceClient, public_url
from harvest.storage import Cache, HarvestError, TooLarge

SIGNED = "https://bucket.s3.amazonaws.com/file.csv?X-Amz-Signature=private-secret"


def client(tmp_path, handler, **kwargs):
    return SourceClient(
        Cache(tmp_path / "cache"),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
        **kwargs,
    )


def test_file_resolves_url_then_immediately_downloads_without_logging_credentials(tmp_path):
    requests = []

    def handler(request):
        requests.append(str(request.url))
        if request.url.host == "psi.nasa.gov":
            return httpx.Response(200, text=SIGNED)
        return httpx.Response(200, content=b"a,b\r\n1,2\r\n")

    instance = client(tmp_path, handler)
    file = {"file_name": "table.csv", "version": 1, "file_size": 10}
    receipt = instance.psi_file(
        "PSI-69", file, tmp_path / "table.csv", study_version="5", limit=100
    )
    assert len(requests) == 2 and requests[1] == SIGNED
    resolver_query = httpx.URL(requests[0]).params
    assert resolver_query["studyVersion"] == "5" and resolver_query["version"] == "1"
    assert receipt.bytes == 10
    for path in (tmp_path / "cache").rglob("*"):
        if path.is_file():
            assert b"private-secret" not in path.read_bytes()
    instance.psi_file("PSI-69", file, tmp_path / "cached.csv", study_version="5", limit=100)
    assert len(requests) == 2
    instance.close()


def test_version_change_invalidates_file_cache(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        return (
            httpx.Response(200, text=SIGNED)
            if request.url.host == "psi.nasa.gov"
            else httpx.Response(200, content=b"data")
        )

    instance = client(tmp_path, handler)
    file = {"file_name": "table.csv", "version": 1}
    for version in ["1", "2"]:
        instance.psi_file("PSI-69", file, tmp_path / version, study_version=version, limit=100)
    assert len(requests) == 4
    instance.close()


def test_expired_signed_url_is_resolved_again(tmp_path):
    counts = {"resolve": 0, "file": 0}

    def handler(request):
        if request.url.host == "psi.nasa.gov":
            counts["resolve"] += 1
            return httpx.Response(200, text=SIGNED)
        counts["file"] += 1
        return httpx.Response(403) if counts["file"] == 1 else httpx.Response(200, content=b"ok")

    instance = client(tmp_path, handler)
    instance.psi_file(
        "PSI-69", {"file_name": "f.csv"}, tmp_path / "f", study_version="1", limit=100
    )
    assert counts == {"resolve": 2, "file": 2}
    instance.close()


def test_transient_errors_retry_and_do_not_leak_signed_url(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, content=b"ok")

    instance = client(tmp_path, handler)
    assert instance._read(SIGNED, 100)[0] == b"ok"
    assert len(calls) == 3
    instance.close()
    failed = client(tmp_path, lambda request: httpx.Response(404))
    with pytest.raises(HarvestError) as exc:
        failed._read(SIGNED, 100)
    assert "private-secret" not in str(exc.value)
    assert str(exc.value).startswith("HTTP 404")
    failed.close()


@pytest.mark.parametrize("declared", [True, False])
def test_size_limit_enforced_before_or_during_stream(tmp_path, declared):
    def handler(request):
        headers = {"content-length": "5"} if declared else {}
        return httpx.Response(200, stream=httpx.ByteStream(b"12345"), headers=headers)

    instance = client(tmp_path, handler)
    with pytest.raises(TooLarge):
        instance.resource("https://www.nasa.gov/file", tmp_path / "file", limit=5)
    assert not (tmp_path / "file").exists()
    instance.close()


def test_offline_mode_never_calls_network_and_checks_cache_integrity(tmp_path):
    def no_network(request):
        pytest.fail("Offline mode attempted network access")

    instance = client(tmp_path, no_network, offline=True)
    url = "https://www.nasa.gov/example"
    with pytest.raises(HarvestError, match="offline"):
        instance.resource(url, tmp_path / "missing")
    instance.cache.save(url, b"cached", content_type="text/plain")
    assert instance.resource(url, tmp_path / "ok").cached
    instance.close()


def test_json_refresh_does_not_use_a_stale_response(tmp_path):
    url = "https://psi.nasa.gov/catalogue"
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"new": True})

    instance = client(tmp_path, handler, refresh=True)
    instance.cache.save(url, b'{"old":true}', content_type="application/json")
    instance.resource(url, tmp_path / "data", json_resource=True)
    assert json.loads((tmp_path / "data").read_text()) == {"new": True}
    assert len(calls) == 1
    instance.close()


@pytest.mark.parametrize(
    "url",
    [
        "http://www.nasa.gov/file",
        "https://evil.example/file",
        "https://nasa.gov.evil.example/file",
        "https://user:password@www.nasa.gov/file",
        "https://www.nasa.gov/file?token=private",
    ],
)
def test_nonpublic_source_urls_are_rejected(url):
    with pytest.raises(HarvestError):
        public_url(url)
