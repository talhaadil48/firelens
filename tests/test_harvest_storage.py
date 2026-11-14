import hashlib

import pytest

from harvest.storage import Cache, HarvestError, TooLarge, safe_name


def test_cache_restores_exact_bytes_and_does_not_link_run_outputs(tmp_path):
    cache = Cache(tmp_path / "cache")
    receipt = cache.save("source-v1", b"source,bytes\r\n1,2\r\n", content_type="text/csv")
    first, second = tmp_path / "first.csv", tmp_path / "second.csv"
    cached = cache.restore("source-v1", first)
    assert cached.cached and cached.sha256 == receipt.sha256
    assert first.read_bytes() == b"source,bytes\r\n1,2\r\n"
    first.write_bytes(b"modified-run")
    cache.restore("source-v1", second)
    assert second.read_bytes() == b"source,bytes\r\n1,2\r\n"


def test_corrupted_cache_is_not_reused(tmp_path):
    cache = Cache(tmp_path / "cache")
    cache.save("source", b"original", content_type="application/pdf")
    blob, _ = cache.paths("source")
    blob.write_bytes(b"tampered")
    assert cache.restore("source", tmp_path / "copy") is None


def test_cache_enforces_strict_limit_and_missing_keys(tmp_path):
    cache = Cache(tmp_path / "cache")
    cache.save("source", b"12345", content_type="text/plain")
    with pytest.raises(TooLarge):
        cache.restore("source", tmp_path / "copy", max_bytes=5)
    assert cache.restore("unknown", tmp_path / "missing") is None
    assert hashlib.sha256(b"12345").hexdigest() == cache.restore("source", tmp_path / "ok").sha256


@pytest.mark.parametrize("name", ["../bad.csv", "..\\bad.csv", "", "..", "nul\x00.csv"])
def test_source_paths_cannot_escape_the_run_folder(name):
    with pytest.raises(HarvestError):
        safe_name(name)


def test_windows_safe_names_keep_originals_identifiable():
    assert safe_name("PSI-69_Experimental table_FLEX.csv") == "PSI-69_Experimental table_FLEX.csv"
    assert ":" not in safe_name("unsafe:name.pdf")
    assert safe_name("CON.txt").startswith("_")
    assert len(safe_name("a" * 300 + ".pdf")) < 100
