"""Offline tests for document selection, page-numbered text and context scraping."""

from datetime import UTC, datetime

import pymupdf

from api.models import Investigation
from harvest.documents import extract
from harvest.harvest import document_candidates, folder_counts, html_to_text, manifest_folder
from harvest.snapshot import document_chunks


def entry(folder: str, name: str, size: float = 1000.0, **extra) -> dict:
    return {
        "file_name": name,
        "file_size": size,
        "version": 2,
        "restricted": False,
        "visible": True,
        "remote_path": f"/Home/psi-data/PSI-26/{folder}/{name}",
        **extra,
    }


def test_document_candidates_take_only_small_reports_and_science_documents():
    manifest = {
        "added": [
            entry("Reports", "PSI-26_Reports_BASS_FinalReport.pdf"),
            entry("Science Documents", "PSI-26_Science Documents_Readme.docx"),
            entry("Raw Data", "PSI-26_Raw Data_video.pdf"),  # never Raw Data
            entry("Presentations", "PSI-26_Presentations_Talk.pdf"),
            entry("Reports", "PSI-26_Reports_Huge.pdf", size=25e6),
            entry("Reports", "PSI-26_Reports_Sheet.xlsx"),
            entry("Reports", "PSI-26_Reports_Locked.pdf", restricted=True),
        ]
    }
    picked = document_candidates(manifest)
    assert [d["file"] for d in picked] == [
        "PSI-26_Reports_BASS_FinalReport.pdf",
        "PSI-26_Science Documents_Readme.docx",
    ]
    assert picked[0] == {
        "file": "PSI-26_Reports_BASS_FinalReport.pdf",
        "folder": "Reports",
        "size": 1000,
        "version": 2,
    }
    assert folder_counts(manifest) == {
        "Presentations": 1,
        "Raw Data": 1,
        "Reports": 4,
        "Science Documents": 1,
    }
    assert manifest_folder({"remote_path": "odd"}) == "Other"


def test_asp_net_form_pages_keep_their_text():
    html = (
        "<html><body><form id='form1'><nav>Menu</nav>"
        "<h2>History</h2><p>In November 1966 NASA turned to the first Apollo mission.</p>"
        "<script>var x = 1;</script></form></body></html>"
    )
    text = html_to_text(html)
    assert "In November 1966 NASA turned to the first Apollo mission." in text
    assert "Menu" not in text and "var x" not in text


def make_pdf(path, pages: list[str]) -> None:
    doc = pymupdf.open()
    for body in pages:
        page = doc.new_page()
        page.insert_text((72, 72), body)
    doc.save(path)
    doc.close()


def test_pdf_text_keeps_page_numbers_and_drops_empty_pages(tmp_path):
    path = tmp_path / "report.pdf"
    make_pdf(
        path,
        [
            "Flame spread over PMMA in opposed flow, page one text.",
            "",
            "Page three: extinction limits were reached near 15 percent oxygen.",
        ],
    )
    text = extract(path)
    assert text.error is None
    assert text.page_count == 3 and text.empty_pages == 1
    assert [n for n, _ in text.pages] == [1, 3]
    assert "extinction limits" in text.pages[1][1]


def test_unreadable_document_is_recorded_not_raised(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4 not really a pdf")
    assert extract(path).error


def test_document_chunks_cite_file_and_page(tmp_path):
    accession = "PSI-26"
    docs = tmp_path / accession / "documents"
    docs.mkdir(parents=True)
    make_pdf(
        docs / "PSI-26_Reports_BASS_FinalReport.pdf",
        [
            "Intro words for the BASS final report on solid fuel burning.",
            "Results: samples self-extinguished at low flow.",
        ],
    )
    inv = Investigation(
        accession=accession,
        title="Burning and Suppression of Solids",
        acronym="BASS",
        research_area="Combustion Science",
        doi="10.60555/58h4-dy80",
        version="4",
        source_url="https://psi.nasa.gov/physci/repo/data/investigations/PSI-26",
        retrieved_at=datetime(2026, 11, 14, tzinfo=UTC),
    )
    report = {
        "investigations": [
            {
                "catalogue": {"accession": accession},
                "documents": [
                    {
                        "file": "PSI-26_Reports_BASS_FinalReport.pdf",
                        "folder": "Reports",
                        "success": True,
                        "sha256": "b" * 64,
                    },
                    {"file": "missing.pdf", "folder": "Reports", "success": False},
                ],
            }
        ]
    }
    chunks, stats = document_chunks([inv], tmp_path, report)
    assert [c["page"] for c in chunks] == [1, 2]
    second = chunks[1]
    assert second["kind"] == "document" and second["doi"] == "10.60555/58h4-dy80"
    assert second["source_file"] == "PSI-26_Reports_BASS_FinalReport.pdf"
    assert second["text"].startswith("BASS (PSI-26) PSI-26_Reports_BASS_FinalReport.pdf, p. 2:")
    assert stats == [
        {
            "accession": accession,
            "file": "PSI-26_Reports_BASS_FinalReport.pdf",
            "folder": "Reports",
            "pages": 2,
            "text_pages": 2,
            "empty_pages": 0,
            "chunks": 2,
            "error": None,
        }
    ]
