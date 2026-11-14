"""Text from harvested Reports and Science Documents, page by page (build-steps 5.2).

Pages keep their 1-based number so answers can cite "BASS final report, p. 7".
DOCX files have no pages; their text comes back as one unit with page ``None``.
Pages with almost no text (scans, figures, blank pages) are dropped and counted, never
guessed at: this module does no OCR.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

MIN_PAGE_CHARS = 40
MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@dataclass
class DocumentText:
    file: str
    pages: list[tuple[int | None, str]] = field(default_factory=list)
    page_count: int = 0
    empty_pages: int = 0
    error: str | None = None


def clean(text: str) -> str:
    text = text.replace("­", "")  # soft hyphens
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # words hyphenated across line ends
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def pdf_pages(path: Path) -> DocumentText:
    import pymupdf

    result = DocumentText(file=path.name)
    with pymupdf.open(path) as doc:
        result.page_count = doc.page_count
        for number, page in enumerate(doc, start=1):
            text = clean(page.get_text("text"))
            if len(text) < MIN_PAGE_CHARS:
                result.empty_pages += 1
                continue
            result.pages.append((number, text))
    return result


def docx_text(path: Path) -> DocumentText:
    import docx

    document = docx.Document(str(path))
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    text = clean("\n".join(parts))
    result = DocumentText(file=path.name, page_count=0)
    if len(text) >= MIN_PAGE_CHARS:
        result.pages.append((None, text))
    return result


def extract(path: Path) -> DocumentText:
    """Never raises for a bad file: the error is recorded and the corpus moves on."""
    try:
        if path.suffix.lower() == ".pdf":
            return pdf_pages(path)
        if path.suffix.lower() == ".docx":
            return docx_text(path)
        return DocumentText(file=path.name, error=f"Unsupported type {path.suffix}")
    except Exception as exc:  # corrupt or encrypted files: record and skip
        return DocumentText(file=path.name, error=f"{type(exc).__name__}: text not extracted")
