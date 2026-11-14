import pytest

from harvest.policy import DOCUMENT_LIMIT, category, select_files, validate_document
from harvest.storage import HarvestError


def file(name, category_name, size=500):
    return {
        "file_name": name,
        "file_size": size,
        "version": 1,
        "s3_path": f"psi-data/PSI-69/{category_name}/{name}",
    }


def test_only_reports_and_science_documents_are_selected_and_tables_deduplicated():
    table = file("table.csv", "Experimental table")
    manifest = {
        "experimentalTable": [table],
        "added": [
            table,
            file("report.pdf", "Reports"),
            file("science.docx", "Science Documents"),
            file("large.pdf", "Reports", DOCUMENT_LIMIT),
            file("data.csv", "Raw Data"),
            file("slides.pdf", "Presentations"),
            file("drawing.pdf", "Engineering Documents"),
        ],
    }
    selected, skipped = select_files("PSI-69", manifest)
    assert {s["file"]["file_name"] for s in selected} == {"table.csv", "report.pdf", "science.docx"}
    assert skipped["duplicate_manifest_entry"] == 1
    assert skipped["category:Raw Data"] == 1
    assert skipped["document_at_or_over_20_MB"] == 1


def test_real_manifest_path_takes_precedence_over_misleading_filename():
    record = file("PSI-69_Reports_not-a-report.csv", "Raw Data")
    assert category("PSI-69", record) == "Raw Data"
    assert select_files("PSI-69", {"added": [record]})[0] == []


def test_filename_category_fallback_for_legacy_metadata():
    assert (
        category("PSI-69", {"file_name": "PSI-69_Science Documents_article.pdf"})
        == "Science Documents"
    )


def test_missing_table_is_not_fabricated():
    selected, skipped = select_files("PSI-69", {"added": []})
    assert selected == [] and skipped == {}


def test_restricted_table_is_recorded_as_a_failure_not_silently_skipped():
    selected, _ = select_files(
        "PSI-69", {"experimentalTable": [{"file_name": "table.csv", "restricted": True}]}
    )
    assert selected[0]["policy_error"]


@pytest.mark.parametrize(
    ("content", "name"),
    [
        (b"<html>login</html>", "report.pdf"),
        (b"not-a-zip", "report.docx"),
        (b"", "report.txt"),
        (b"<Error>not found</Error>", "report.txt"),
    ],
)
def test_document_error_pages_are_rejected(content, name):
    with pytest.raises(HarvestError):
        validate_document(content, name)
