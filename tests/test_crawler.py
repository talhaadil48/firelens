import pytest

from harvest.crawler import (
    HTMLTextExtractor,
    csv_summary,
    read_signed_url,
)


def test_html_text_extractor_removes_scripts_and_styles():
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Page</title>
        <style>body { background: black; }</style>
        <script>alert('malicious');</script>
    </head>
    <body>
        <nav><a href="/">Home</a></nav>
        <h1>Spacecraft Fire Safety</h1>
        <p>Microgravity combustion behaves differently than on Earth.</p>
        <div class="content">
            <p>Diffusion is the primary transport mechanism without buoyancy.</p>
        </div>
        <footer>Copyright 2026</footer>
    </body>
    </html>
    """
    extractor = HTMLTextExtractor()
    extractor.feed(html)
    text = extractor.get_text()

    assert "Spacecraft Fire Safety" in text
    assert "Microgravity combustion behaves differently" in text
    assert "Diffusion is the primary transport mechanism" in text
    assert "alert('malicious')" not in text
    assert "background: black" not in text
    assert "Home" not in text
    assert "Copyright" not in text


def test_read_signed_url_validation():
    valid = "https://psi-curation-prod.s3.amazonaws.com/test.csv?AWSAccessKeyId=KEY&Signature=SIG"
    assert read_signed_url(valid) == valid
    assert read_signed_url(f'"{valid}"') == valid
    assert read_signed_url(f"'{valid}'") == valid

    with pytest.raises(ValueError, match="trusted HTTPS download URL"):
        read_signed_url("http://insecure-host.com/file.csv")

    with pytest.raises(ValueError, match="trusted HTTPS download URL"):
        read_signed_url("https://malicious-domain.com/file.csv")


def test_csv_summary_validates_and_extracts_headers():
    data = b"test_id,material,oxygen,pressure\n1,PMMA,0.21,101.3\n2,PE,0.30,70.0\n"
    summary = csv_summary(data)
    assert summary["headers"] == ["test_id", "material", "oxygen", "pressure"]
    assert summary["physical_data_rows"] == 2
    assert summary["encoding"] == "utf-8-sig"
    assert len(summary["sha256"]) == 64


def test_csv_summary_rejects_html():
    with pytest.raises(ValueError, match="Expected CSV content"):
        csv_summary(b"<!DOCTYPE html><html><body>Error</body></html>")
