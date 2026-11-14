import hashlib
import json
from pathlib import Path

import httpx
import pytest

from harvest.client import SourceClient
from harvest.context import html_text, pdf_text
from harvest.run import get_catalogue, harvest
from harvest.storage import Cache, HarvestError


def hit(accession, area="Combustion Science"):
    return {"_id": accession, "_source": {"Accession": accession, "Research Area": area}}


def test_catalogue_paginates_every_investigation_before_filtering(tmp_path):
    requested = []

    def handler(request):
        offset = int(request.url.params["from"])
        requested.append(offset)
        rows = [hit("PSI-1", "Fluid Physics"), hit("PSI-2"), hit("PSI-3"), hit("PSI-4")]
        return httpx.Response(
            200, json={"hits": {"total": {"value": 4}, "hits": rows[offset : offset + 2]}}
        )

    client = SourceClient(Cache(tmp_path / "cache"), transport=httpx.MockTransport(handler))
    found, report = get_catalogue(client, tmp_path / "catalogue", page_size=2)
    assert requested == [0, 2]
    assert [row["_source"]["Accession"] for row in found] == ["PSI-2", "PSI-3", "PSI-4"]
    assert report["total_records"] == 4 and report["combustion_count"] == 3
    assert len(list((tmp_path / "catalogue").glob("page-*.json"))) == 2
    client.close()


def test_incomplete_pagination_cannot_be_marked_complete(tmp_path):
    client = SourceClient(
        Cache(tmp_path / "cache"),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"hits": {"total": 10, "hits": [hit("PSI-69")]}}
            )
        ),
    )
    with pytest.raises(HarvestError, match="pagination"):
        get_catalogue(client, tmp_path / "catalogue", page_size=2)
    client.close()


def configuration(tmp_path):
    path = tmp_path / "context.yaml"
    path.write_text(
        "sources:\n  - id: context\n    topic: Test context\n    url: https://www.nasa.gov/context\n"
    )
    return path


def fake_nasa(request, fail_table=False):
    if request.url.path.endswith("/search"):
        return httpx.Response(
            200, json={"hits": {"total": 2, "hits": [hit("PSI-69"), hit("PSI-1", "Fluid Physics")]}}
        )
    if request.url.path.endswith("/investigations/PSI-69"):
        table = {"file_name": "table.csv", "file_size": 10, "version": 1}
        return httpx.Response(
            200,
            json={
                "accession": "PSI-69",
                "title": "Synthetic integration fixture",
                "version": 1,
                "researchArea": "Combustion Science",
                "public": True,
                "restricted": False,
                "doi": "10.0000/synthetic-test",
                "licenseIdentifier": "CC0-1.0",
                "experimentHardware": "Synthetic hardware",
                "experimentalTable": [table],
                "added": [
                    {"file_name": "PSI-69_Reports_report.pdf", "file_size": 50, "version": 1},
                    {"file_name": "PSI-69_Raw Data_large.zip", "file_size": 999999999},
                ],
            },
        )
    if request.url.path.endswith("/download"):
        name = request.url.params["file"]
        return httpx.Response(
            200,
            text="https://bucket.s3.amazonaws.com/" + name + "?X-Amz-Signature=not-to-be-logged",
        )
    if request.url.host == "bucket.s3.amazonaws.com":
        if request.url.path.endswith(".csv"):
            return (
                httpx.Response(404)
                if fail_table
                else httpx.Response(200, content=b"a,b\r\n1,2\r\n")
            )
        return httpx.Response(200, content=b"%PDF-1.7\nsynthetic-report")
    if request.url.path == "/context":
        return httpx.Response(
            200,
            text="<html><title>NASA context test</title><main>"
            + "<nav>discard navigation</nav>"
            + "Test context with source evidence. " * 20
            + "</main></html>",
        )
    pytest.fail(f"Unexpected public fixture request: {request.url.path}")


def test_complete_harvest_and_offline_replay_preserve_bytes_and_audit(tmp_path):
    sources = configuration(tmp_path)
    root = tmp_path / "raw"
    report = harvest(root, "first", sources, transport=httpx.MockTransport(fake_nasa))
    assert report["status"] == "complete"
    with pytest.raises(HarvestError, match="immutable"):
        harvest(root, "first", sources, transport=httpx.MockTransport(fake_nasa))
    assert report["counts"]["manifests"] == 1
    assert report["counts"]["tables"] == 1
    assert report["counts"]["documents"] == 1
    assert report["counts"]["context_sources"] == 1
    assert (root / "first/PSI-69/table.csv").read_bytes() == b"a,b\r\n1,2\r\n"
    assert report["investigations"][0]["doi"] == "10.0000/synthetic-test"
    assert report["investigations"][0]["hardware"] == "Synthetic hardware"
    for record in report["investigations"][0]["files"]:
        path = root / "first" / record["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["receipt"]["sha256"]
    assert "not-to-be-logged" not in json.dumps(report)
    assert "not-to-be-logged" not in (root / "first/HARVEST_LOG.md").read_text()
    assert not list((root / "first").rglob("*large.zip"))

    def no_network(request):
        pytest.fail("Offline replay attempted a network request")

    replay = harvest(
        root, "second", sources, offline=True, transport=httpx.MockTransport(no_network)
    )
    assert replay["status"] == "complete"
    assert replay["counts"]["cache_hits"] == 2
    assert json.loads((root / "latest-harvest.json").read_text())["run_id"] == "second"
    assert (root / "first/PSI-69/table.csv").read_bytes() == b"a,b\r\n1,2\r\n"


def test_missing_table_is_recorded_and_does_not_publish_latest(tmp_path):
    report = harvest(
        tmp_path / "raw",
        "partial",
        configuration(tmp_path),
        transport=httpx.MockTransport(lambda request: fake_nasa(request, fail_table=True)),
    )
    assert report["status"] == "partial"
    assert report["counts"]["failures"] == 1
    assert not (tmp_path / "raw/latest-harvest.json").exists()
    assert (tmp_path / "raw/partial/HARVEST_LOG.md").exists()
    assert "HTTP 404" in (tmp_path / "raw/partial/HARVEST_LOG.md").read_text()
    assert "not-to-be-logged" not in json.dumps(report)


def test_empty_or_wrong_catalogue_writes_a_failure_log(tmp_path):
    report = harvest(
        tmp_path / "raw",
        "empty",
        configuration(tmp_path),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"hits": {"total": 0, "hits": []}})
        ),
    )
    assert report["status"] == "failed" and report["counts"]["failures"] == 1
    assert "fatal_error" in report
    assert (tmp_path / "raw/empty/HARVEST_LOG.md").exists()


def test_context_text_removes_navigation_scripts_and_records_actual_article_text():
    body = (
        "<html><title>Source title</title><main><nav>Hidden nav</nav><script>evil()</script>"
        + "NASA context. " * 30
        + "</main></html>"
    )
    title, text = html_text(body.encode())
    assert title == "Source title" and "NASA context." in text
    assert "Hidden nav" not in text and "evil" not in text
    with pytest.raises(HarvestError):
        html_text(b"<html><main>Loading...</main></html>")
    with pytest.raises(HarvestError):
        pdf_text(b"not a PDF")


@pytest.mark.parametrize("run_id", ["../escape", "a/b", "", ".", "..\\escape"])
def test_run_id_cannot_escape_output_directory(tmp_path, run_id):
    with pytest.raises(HarvestError):
        harvest(tmp_path, run_id, Path("unused"))


def test_audit_detects_tampered_source_files(tmp_path):
    from harvest.verify import verify

    root = tmp_path / "raw"
    harvest(root, "audit", configuration(tmp_path), transport=httpx.MockTransport(fake_nasa))
    assert verify(root / "audit")["success"]
    text_path = root / "audit/context/context.txt"
    original_text = text_path.read_bytes()
    text_path.write_bytes(original_text + b"tampered extracted evidence")
    assert not verify(root / "audit")["integrity_ok"]
    text_path.write_bytes(original_text)
    (root / "audit/PSI-69/table.csv").write_bytes(b"changed data")
    result = verify(root / "audit")
    assert not result["success"]
    assert any("Checksum" in message for message in result["failures"])


def test_duplicate_catalogue_pages_cannot_hide_missing_investigations(tmp_path):
    client = SourceClient(
        Cache(tmp_path / "cache"),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"hits": {"total": 4, "hits": [hit("PSI-69"), hit("PSI-26")]}}
            )
        ),
    )
    with pytest.raises(HarvestError, match="unique records"):
        get_catalogue(client, tmp_path / "catalogue", page_size=2)
    client.close()


def test_malformed_catalogue_response_still_produces_a_failure_log(tmp_path):
    report = harvest(
        tmp_path / "raw",
        "malformed",
        configuration(tmp_path),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])),
    )
    assert report["status"] == "failed"
    assert "JSON object" in report["fatal_error"]
    assert "JSON object" in (tmp_path / "raw/malformed/HARVEST_LOG.md").read_text()
