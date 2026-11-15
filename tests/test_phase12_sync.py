from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit

import httpx
from fastapi.testclient import TestClient

from api.config import Settings
from api.main import app, configure_runtime
from sync.run import main as sync_main
from sync.run import run_sync, upload_snapshot_to_blob


def _write_empty_sources(path: Path) -> Path:
    path.write_text("sources: []\n", encoding="utf-8")
    return path


def _make_hit(
    accession: str,
    version: int | str,
    release_date: str,
    modified_date: str,
    title: str | None = None,
) -> dict[str, Any]:
    return {
        "_id": accession,
        "_source": {
            "Accession": accession,
            "Title": title or f"{accession} Combustion Study",
            "Research Area": "Combustion Science",
            "Version": str(version),
            "Release Date": release_date,
            "Modified Date": modified_date,
            "DOI": f"10.60555/test-{accession.lower()}",
        },
    }


def _make_manifest(
    accession: str,
    version: int | str,
    release_date: str,
    modified_date: str,
    table_name: str,
    table_bytes: bytes,
) -> dict[str, Any]:
    return {
        "accession": accession,
        "title": f"{accession} Combustion Study",
        "doi": f"10.60555/test-{accession.lower()}",
        "version": str(version),
        "releaseDate": release_date,
        "modifiedDate": modified_date,
        "researchArea": "Combustion Science",
        "public": True,
        "restricted": False,
        "licenseIdentifier": "CC0",
        "licenseName": "Creative Commons Zero 1.0",
        "licenseLink": "https://creativecommons.org/publicdomain/zero/1.0/",
        "experimentHardware": "CIR / MSG",
        "experimentalTable": [
            {
                "file_name": table_name,
                "file_size": len(table_bytes),
                "version": int(version),
                "s3_version_id": f"{accession.lower()}-v{version}",
            }
        ],
        "added": [],
    }


class _MockPsiServer:
    """In-memory mock PSI REST + signed-S3 HTTP transport for incremental sync tests."""

    def __init__(self) -> None:
        self.hits: list[dict[str, Any]] = []
        self.manifests: dict[str, dict[str, Any]] = {}
        self.files: dict[tuple[str, str, str], bytes] = {}
        self.requests: list[str] = []

    def set_study(
        self,
        accession: str,
        *,
        version: int | str,
        release_date: str,
        modified_date: str,
        table_name: str,
        table_bytes: bytes,
    ) -> None:
        hit = _make_hit(accession, version, release_date, modified_date)
        self.hits = [h for h in self.hits if h["_id"] != accession] + [hit]
        self.hits.sort(key=lambda item: int(item["_id"].split("-")[1]))
        self.manifests[accession] = _make_manifest(
            accession, version, release_date, modified_date, table_name, table_bytes
        )
        self.files[(accession, table_name, str(version))] = table_bytes

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(str(request.url))
            parsed = urlsplit(str(request.url))
            path = parsed.path

            if path == "/geode-py/ws/repo/search":
                return httpx.Response(
                    200,
                    json={
                        "hits": {
                            "total": len(self.hits),
                            "hits": self.hits,
                        }
                    },
                )

            if path.startswith("/geode-py/ws/repo/investigations/"):
                accession = path.rsplit("/", 1)[-1]
                manifest = self.manifests.get(accession)
                if manifest is None:
                    return httpx.Response(404, json={"error": "not found"})
                return httpx.Response(200, json=manifest)

            if path.startswith("/geode-py/ws/studies/") and path.endswith("/download"):
                parts = path.split("/")
                accession = parts[4]
                qs = parse_qs(parsed.query)
                file_name = qs["file"][0]
                study_ver = qs["studyVersion"][0]
                signed_url = (
                    f"https://psi.nasa.gov/mock-s3/{accession}/{study_ver}/{quote(file_name)}"
                )
                return httpx.Response(200, text=json.dumps(signed_url))

            if path.startswith("/mock-s3/"):
                _, _, accession, study_ver, raw_file_name = path.split("/", 4)
                file_name = unquote(raw_file_name)
                payload = self.files.get((accession, file_name, study_ver))
                if payload is None:
                    return httpx.Response(404, content=b"missing")
                return httpx.Response(
                    200,
                    content=payload,
                    headers={"Content-Type": "text/csv"},
                )

            return httpx.Response(404, content=b"unhandled route")

        return httpx.MockTransport(handler)


def _psi69_csv_bytes(*, extra_row: bool = False) -> bytes:
    rows = [
        (
            "FLEX Test #,Test Date,Fuel,Droplet initial diameter; mm,"
            "O initial ambient composition; mole fraction,Ambient pressure; mmHg,"
            "Test end,N initial ambient composition; mole fraction,"
            "CO initial ambient composition; mole fraction,"
            "He initial ambient composition; mole fraction,"
            "Visible flame extinction diameter; mm,Burning rate; mm,Burn time; s"
        ),
        "FLEX-01,01/15/2010,Heptane,3.2,0.21,760.0,Extinction,0.79,0,0,1.1,0.55,5.8",
    ]
    if extra_row:
        rows.append("FLEX-02,01/16/2010,Methanol,2.8,0.24,760.0,Completion,0.76,0,0,0.9,0.48,4.9")
    return ("\n".join(rows) + "\n").encode("cp1252")


def _psi25_csv_bytes(*, o2_pct: str = "18.5", include_pmma: bool = False) -> bytes:
    rows = [
        (
            "Test #,Date,Fuel Sample Material,Calibrated  initial O2 % by vol ,"
            "Calibrated final O2 % by vol,Initial CO2 % by vol,Final CO2 % by vol,"
            "Initial CO (ppm),Final CO (ppm)"
        ),
        f"BASS-01,05/12/2014,Cellulose,{o2_pct},16.0,0.0,2.1,0,120",
    ]
    if include_pmma:
        rows.append("BASS-02,05/14/2014,PMMA rod,21.0,18.2,0.0,2.8,0,150")
    return ("\n".join(rows) + "\n").encode("utf-8-sig")


def _psi777_unmapped_csv_bytes() -> bytes:
    return (
        b"Sample Label,Chamber Flow (cm/s),Peak Heat Flux (W/cm2)\n"
        b"Nomex-A,12.5,3.4\n"
        b"Nomex-B,15.0,4.1\n"
    )


def _seed_initial_snapshot(tmp_path: Path, server: _MockPsiServer) -> tuple[Path, Path, Path, Path]:
    raw_root = tmp_path / "raw"
    snapshots_dir = tmp_path / "snapshots"
    sources_file = _write_empty_sources(tmp_path / "sources.yaml")
    server.set_study(
        "PSI-69",
        version=1,
        release_date="2020-06-01",
        modified_date="2020-06-01",
        table_name="PSI-69_Experimental table_FLEX.csv",
        table_bytes=_psi69_csv_bytes(),
    )
    server.set_study(
        "PSI-25",
        version=1,
        release_date="2021-03-15",
        modified_date="2021-03-15",
        table_name="PSI-25_Experimental table_BASS-II.csv",
        table_bytes=_psi25_csv_bytes(),
    )
    first = run_sync(
        raw_root=raw_root,
        snapshots_dir=snapshots_dir,
        sources_file=sources_file,
        run_id="sync-v1",
        snapshot_id="sync-v1",
        force=True,
        transport=server.transport(),
    )
    assert first["status"] == "synced"
    return raw_root, snapshots_dir, sources_file, raw_root / "sync-v1"


def test_sync_up_to_date_skips_rebuild_and_network_harvest(tmp_path: Path) -> None:
    server = _MockPsiServer()
    raw_root, snapshots_dir, sources_file, base_raw_dir = _seed_initial_snapshot(tmp_path, server)
    before_latest = (snapshots_dir / "latest.json").read_text(encoding="utf-8")
    server.requests.clear()

    result = run_sync(
        raw_root=raw_root,
        base_raw_dir=base_raw_dir,
        snapshots_dir=snapshots_dir,
        sources_file=sources_file,
        run_id="sync-noop",
        snapshot_id="sync-noop",
        transport=server.transport(),
    )

    assert result["status"] == "up_to_date"
    assert result["changed"] is False
    assert result["snapshot_id"] == "sync-v1"
    assert result["unchanged"] == ["PSI-25", "PSI-69"]
    assert result["added"] == []
    assert result["updated"] == []
    assert not (snapshots_dir / "sync-noop").exists()
    assert (snapshots_dir / "latest.json").read_text(encoding="utf-8") == before_latest
    # Only the catalogue check ran; no manifests or files were fetched.
    assert len(server.requests) == 1
    assert "/geode-py/ws/repo/search" in server.requests[0]


def test_sync_incremental_harvests_only_changed_and_new_studies_and_flags_unmapped(
    tmp_path: Path,
) -> None:
    server = _MockPsiServer()
    raw_root, snapshots_dir, sources_file, base_raw_dir = _seed_initial_snapshot(tmp_path, server)
    server.requests.clear()

    # PSI-69 stays at version 1; PSI-25 bumps to version 2; PSI-777 is newly added (unmapped CSV).
    server.set_study(
        "PSI-25",
        version=2,
        release_date="2026-02-01",
        modified_date="2026-02-01",
        table_name="PSI-25_Experimental table_BASS-II.csv",
        table_bytes=_psi25_csv_bytes(include_pmma=True),
    )
    server.set_study(
        "PSI-777",
        version=1,
        release_date="2026-03-01",
        modified_date="2026-03-01",
        table_name="PSI-777_Experimental_Table.csv",
        table_bytes=_psi777_unmapped_csv_bytes(),
    )

    result = run_sync(
        raw_root=raw_root,
        base_raw_dir=base_raw_dir,
        snapshots_dir=snapshots_dir,
        sources_file=sources_file,
        run_id="sync-v2",
        snapshot_id="sync-v2",
        transport=server.transport(),
    )

    assert result["status"] == "synced"
    assert result["changed"] is True
    assert result["previous_snapshot_id"] == "sync-v1"
    assert result["snapshot_id"] == "sync-v2"
    assert result["unchanged"] == ["PSI-69"]
    assert result["updated"] == ["PSI-25"]
    assert result["added"] == ["PSI-777"]
    assert result["unmapped_tables"] == [
        {"accession": "PSI-777", "source_file": "PSI-777_Experimental_Table.csv"}
    ]

    # PSI-69 was reused from base_raw_dir without issuing manifest or file requests.
    assert not any("PSI-69" in url for url in server.requests)
    assert any("/investigations/PSI-25" in url for url in server.requests)
    assert any("/investigations/PSI-777" in url for url in server.requests)

    snap_v2 = snapshots_dir / "sync-v2"
    invs = json.loads((snap_v2 / "investigations.json").read_text(encoding="utf-8"))["items"]
    by_acc = {item["accession"]: item for item in invs}
    assert set(by_acc) == {"PSI-25", "PSI-69", "PSI-777"}
    psi777 = by_acc["PSI-777"]
    assert any(
        "No scalar column map is configured for PSI-777_Experimental_Table.csv" in gap
        for gap in psi777["data_gaps"]
    )
    assert "review_status" not in psi777

    configure_runtime(Settings(mode="snapshot", snapshots_dir=snapshots_dir))
    with TestClient(app) as client:
        psi777_rows = client.get("/tests", params={"accession": "PSI-777"}).json()["items"]
        psi25_rows = client.get("/tests", params={"accession": "PSI-25"}).json()["items"]

    assert len(psi777_rows) == 2
    assert all(row["record_kind"] == "grouped_summary" for row in psi777_rows)
    assert all(row["o2_fraction"] is None for row in psi777_rows)
    cells = {cell["column"]: cell["value"] for cell in psi777_rows[0]["source_cells"]}
    assert cells["Sample Label"] == "Nomex-A"
    assert cells["Peak Heat Flux (W/cm2)"] == "3.4"

    assert len(psi25_rows) == 2
    assert {row["fuel"] for row in psi25_rows} == {"Cellulose", "PMMA rod"}

    snapshot_md = (snap_v2 / "SNAPSHOT.md").read_text(encoding="utf-8")
    assert "## Phase 12 Incremental Sync" in snapshot_md
    assert "PSI-777/PSI-777_Experimental_Table.csv" in snapshot_md


def test_sync_api_hot_swaps_within_15_minutes_and_updates_meta_badge(tmp_path: Path) -> None:
    server = _MockPsiServer()
    raw_root, snapshots_dir, sources_file, base_raw_dir = _seed_initial_snapshot(tmp_path, server)

    # Simulate an upstream PSI catalogue release published after v1 was built.
    server.set_study(
        "PSI-25",
        version=2,
        release_date="2026-02-01",
        modified_date="2026-02-01",
        table_name="PSI-25_Experimental table_BASS-II.csv",
        table_bytes=_psi25_csv_bytes(include_pmma=True),
    )

    now = [100.0]
    live_hits = list(server.hits)
    settings = Settings(
        mode="snapshot",
        snapshots_dir=snapshots_dir,
        snapshot_refresh_seconds=900,
        catalogue_cache_seconds=3600,
        enable_live_catalogue_check=True,
    )
    configure_runtime(
        settings,
        catalogue_fetcher=lambda: list(live_hits),
        clock=lambda: now[0],
    )

    with TestClient(app) as client:
        meta_before = client.get("/meta")
        assert meta_before.status_code == 200
        body_before = meta_before.json()
        assert body_before["snapshot_id"] == "sync-v1"
        assert body_before["investigation_count"] == 2
        assert body_before["test_count"] == 2
        assert body_before["new_releases_since_snapshot"] == 1

        # Also add PSI-777 before running the Phase 12 sync worker.
        server.set_study(
            "PSI-777",
            version=1,
            release_date="2026-03-01",
            modified_date="2026-03-01",
            table_name="PSI-777_Experimental_Table.csv",
            table_bytes=_psi777_unmapped_csv_bytes(),
        )
        live_hits[:] = server.hits

        sync_result = run_sync(
            raw_root=raw_root,
            base_raw_dir=base_raw_dir,
            snapshots_dir=snapshots_dir,
            sources_file=sources_file,
            run_id="sync-v2",
            snapshot_id="sync-v2",
            transport=server.transport(),
        )
        assert sync_result["status"] == "synced"

        # Before 15 minutes have elapsed, the running API stays on sync-v1.
        now[0] = 500.0
        meta_mid = client.get("/meta").json()
        assert meta_mid["snapshot_id"] == "sync-v1"

        # At 15 minutes (900 seconds), the API hot-swaps to sync-v2 with zero restart.
        now[0] = 1000.0
        meta_after = client.get("/meta")
        assert meta_after.status_code == 200
        body_after = meta_after.json()
        assert body_after["snapshot_id"] == "sync-v2"
        assert body_after["investigation_count"] == 3
        assert body_after["test_count"] == 5
        assert body_after["new_releases_since_snapshot"] == 0

        inv_resp = client.get("/investigations/PSI-777")
        assert inv_resp.status_code == 200
        assert inv_resp.json()["accession"] == "PSI-777"
        psi25_resp = client.get("/investigations/PSI-25")
        assert psi25_resp.status_code == 200
        assert psi25_resp.json()["version"] == "2"


def test_sync_blob_upload_orders_files_before_latest_pointer_and_shared_key_auth(
    tmp_path: Path,
) -> None:
    server = _MockPsiServer()
    _, snapshots_dir, _, _ = _seed_initial_snapshot(tmp_path, server)
    pointer_data = json.loads((snapshots_dir / "latest.json").read_text(encoding="utf-8"))
    from api.models import SnapshotPointer

    pointer = SnapshotPointer.model_validate(pointer_data)

    uploaded_order: list[str] = []
    returned = upload_snapshot_to_blob(
        snapshots_dir,
        pointer,
        blob_uploader=lambda blob_path, _data, _ct: uploaded_order.append(blob_path),
    )
    assert uploaded_order == returned
    assert uploaded_order[-1] == "latest.json"
    assert all(path.startswith("sync-v1/") for path in uploaded_order[:-1])

    seen_puts: list[tuple[str, dict[str, str]]] = []

    def blob_handler(request: httpx.Request) -> httpx.Response:
        seen_puts.append((request.url.path, dict(request.headers)))
        return httpx.Response(201)

    fake_key = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
    http_uploaded = upload_snapshot_to_blob(
        snapshots_dir,
        pointer,
        account_url="https://firelenstest.blob.core.windows.net",
        container="snapshots",
        storage_key=fake_key,
        transport=httpx.MockTransport(blob_handler),
    )
    assert http_uploaded[-1] == "latest.json"
    assert seen_puts[-1][0] == "/snapshots/latest.json"
    assert seen_puts[-1][1].get("cache-control") == "no-cache"
    for _, headers in seen_puts:
        assert headers.get("x-ms-blob-type") == "BlockBlob"
        assert headers.get("authorization", "").startswith("SharedKey firelenstest:")


def test_sync_cli_main_entrypoint(tmp_path: Path, capsys: Any) -> None:
    server = _MockPsiServer()
    raw_root, snapshots_dir, sources_file, base_raw_dir = _seed_initial_snapshot(tmp_path, server)
    capsys.readouterr()

    noop_code = sync_main(
        [
            "--raw-root",
            str(raw_root),
            "--base-raw-dir",
            str(base_raw_dir),
            "--snapshots-dir",
            str(snapshots_dir),
            "--sources-file",
            str(sources_file),
            "--offline",
        ]
    )
    assert noop_code == 0
    noop_out = json.loads(capsys.readouterr().out)
    assert noop_out["status"] == "up_to_date"
    assert noop_out["snapshot_id"] == "sync-v1"

    exit_code = sync_main(
        [
            "--raw-root",
            str(raw_root),
            "--base-raw-dir",
            str(base_raw_dir),
            "--snapshots-dir",
            str(snapshots_dir),
            "--sources-file",
            str(sources_file),
            "--run-id",
            "cli-run",
            "--snapshot-id",
            "cli-snap",
            "--force",
            "--offline",
        ]
    )
    assert exit_code == 0
    stdout_text = capsys.readouterr().out
    json_start = stdout_text.rfind("\n{\n")
    payload_text = stdout_text[json_start + 1 :] if json_start != -1 else stdout_text
    captured = json.loads(payload_text)
    assert captured["status"] == "synced"
    assert captured["snapshot_id"] == "cli-snap"
    assert (snapshots_dir / "cli-snap" / "sync_report.json").exists()
