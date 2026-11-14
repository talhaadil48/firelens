import pytest

from harvest.spike import csv_summary, read_signed_url


@pytest.mark.parametrize(
    "payload",
    [
        "https://example.org/not-nasa?token=secret",
        "http://psi.nasa.gov/file",
        "<html>not a URL</html>",
        "https://evilamazonaws.com/file",
    ],
)
def test_download_resolver_rejects_unexpected_hosts(payload):
    with pytest.raises(ValueError):
        read_signed_url(payload)


def test_signed_url_is_preserved_including_query_and_quoting():
    url = "https://psi-curation-prod.s3.amazonaws.com/file.csv?signature=a%2Bb&token=abc"
    assert read_signed_url('"' + url + '"') == url
    assert read_signed_url(url + "\n") == url


def test_legacy_encoding_and_quoted_csv_cells_are_preserved():
    raw = 'title,value\r\n"long–name, quoted",2\r\n'.encode("cp1252")
    summary = csv_summary(raw)
    assert summary["headers"] == ["title", "value"]
    assert summary["physical_data_rows"] == 1
    assert summary["encoding"] == "cp1252"


@pytest.mark.parametrize("content", [b"<html>login</html>", b"<?xml error>", b"not a CSV"])
def test_html_and_non_table_downloads_are_not_accepted(content):
    with pytest.raises(ValueError):
        csv_summary(content)
