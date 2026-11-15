"""Capture readable NASA context with URLs; this is not experiment evidence extraction."""

import hashlib
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urljoin

import pymupdf
import yaml
from bs4 import BeautifulSoup

from harvest.client import SourceClient, public_url
from harvest.storage import HarvestError, atomic_bytes, safe_name, write_json


def html_text(content: bytes) -> tuple[str, str]:
    soup = BeautifulSoup(content, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else "Untitled source"
    main = soup.find("main") or soup.find("article") or soup.body or soup
    for element in main.select("script, style, nav, footer, header, noscript, iframe, form"):
        element.decompose()
    text = "\n".join(
        line.strip() for line in main.get_text("\n", strip=True).splitlines() if line.strip()
    )
    if len(text) < 200:
        raise HarvestError("Source has insufficient readable text (possibly a JavaScript shell)")
    return title, text


def pdf_text(content: bytes) -> str:
    if not content.startswith(b"%PDF-"):
        raise HarvestError("Expected a PDF signature")
    try:
        with pymupdf.open(stream=content, filetype="pdf") as document:
            text = "\n\n".join(
                f"--- PDF page {i + 1} ---\n{page.get_text()}" for i, page in enumerate(document)
            )
    except Exception:
        raise HarvestError("Could not extract text from context PDF") from None
    if len(text.strip()) < 200:
        raise HarvestError("Context PDF has insufficient extractable text")
    return text


def capture(source: dict, folder: Path, client: SourceClient) -> dict:
    identifier = safe_name(source["id"])
    target = folder / (identifier + ".html")
    attempts = []
    urls = [source["url"], *source.get("fallback_urls", [])]
    for candidate in urls:
        url = public_url(candidate)
        try:
            receipt = client.resource(url, target, json_resource=True, validator=html_text)
            title, text = html_text(target.read_bytes())
            attempts.append({"url": url, "status": "success"})
            break
        except (HarvestError, ValueError, OSError) as exc:
            error = str(exc) if isinstance(exc, HarvestError) else type(exc).__name__
            attempts.append({"url": url, "status": "failed", "error": error})
    else:
        raise HarvestError("No readable context source; " + "; ".join(a["error"] for a in attempts))

    record = {
        "id": identifier,
        "topic": source["topic"],
        "url": url,
        "requested_url": source["url"],
        "source_attempts": attempts,
        "used_fallback": url != source["url"],
        "title": title,
        "status": "success",
        "receipt": asdict(receipt),
        "text_file": identifier + ".txt",
        "selection": (
            "configured_fallback_NASA_source"
            if url != source["url"]
            else "configured_primary_NASA_source"
        ),
    }
    if source.get("follow_pdf"):
        soup = BeautifulSoup(target.read_bytes(), "html.parser")
        pdfs = [
            urljoin(url, a["href"]) for a in soup.select("a[href]") if ".pdf" in a["href"].lower()
        ]
        # Prefer the linked combustion guide; never choose an unrelated global-nav PDF.
        candidates = [p for p in pdfs if "combust" in p.lower() or "rg-6" in p.lower()]
        if not candidates:
            raise HarvestError("The researcher's guide page has no identifiable guide PDF link")
        pdf_url = public_url(candidates[0])
        pdf_path = folder / (identifier + ".pdf")
        pdf_receipt = client.resource(pdf_url, pdf_path, validator=pdf_text)
        text += "\n\nPDF source: " + pdf_url + "\n\n" + pdf_text(pdf_path.read_bytes())
        record["pdf"] = {"url": pdf_url, "file": pdf_path.name, "receipt": asdict(pdf_receipt)}
    output = f"Title: {title}\nSource URL: {url}\nRetrieved: {receipt.retrieved_at}\n\n{text}\n"
    text_bytes = output.encode()
    record["text_integrity"] = {
        "sha256": hashlib.sha256(text_bytes).hexdigest(),
        "bytes": len(text_bytes),
    }
    atomic_bytes(folder / record["text_file"], text_bytes)
    write_json(folder / (identifier + ".source.json"), record)
    return record


def context_sources(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        raise HarvestError("Context configuration must contain a sources list")
    identifiers = [s["id"] for s in data["sources"]]
    if len(set(identifiers)) != len(identifiers):
        raise HarvestError("Context source IDs must be unique")
    for source in data["sources"]:
        public_url(source["url"])
        for fallback in source.get("fallback_urls", []):
            public_url(fallback)
        safe_name(source["id"])
    return data
