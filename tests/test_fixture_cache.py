"""Independent data processes must not overwrite the evidence behind source hashes."""

import hashlib
import json

import httpx

from scripts import build_fixtures


def test_fixture_refresh_preserves_spike_cache_and_retains_hashed_bytes(tmp_path, monkeypatch):
    spike = tmp_path / "raw/spike/PSI-69/manifest.json"
    spike.parent.mkdir(parents=True)
    spike.write_text('{"original_spike_cache": true}')
    monkeypatch.setattr(build_fixtures, "ROOT", tmp_path)
    monkeypatch.setattr(build_fixtures, "SAMPLE", tmp_path / "snapshots/sample")
    (tmp_path / "docs/context").mkdir(parents=True)

    def fake_fetch(client, url):
        # Synthetic unit-test metadata exists only in pytest's temporary folder.
        accession = url.rsplit("/", 1)[-1]
        return httpx.Response(
            200,
            json={
                "title": f"Synthetic cache test {accession}",
                "version": 1,
                "researchArea": "Combustion Science",
                "licenseIdentifier": "CC0-1.0",
            },
        )

    monkeypatch.setattr(build_fixtures, "fetch", fake_fetch)
    build_fixtures.build()
    assert spike.read_text() == '{"original_spike_cache": true}'
    inventory = json.loads((tmp_path / "docs/context/source-inventory.json").read_text())
    records = json.loads((tmp_path / "snapshots/sample/investigations.json").read_text())["items"]
    for item, record in zip(inventory, records, strict=True):
        retained = tmp_path / "raw/fixtures" / item["accession"] / "manifest.json"
        digest = hashlib.sha256(retained.read_bytes()).hexdigest()
        assert item["manifest_sha256"] == digest
        assert record["citations"][0]["provenance"]["source_sha256"] == digest
