"""PDF text extraction + whitespace cleaning for uploaded resumes.

Resumes are processed fully in memory — nothing is ever written to disk,
so there are no temporary files to clean up. Only the first MAX_PAGES
pages are parsed to keep oversized/malicious uploads cheap to handle.
"""

import logging
import re

logger = logging.getLogger("pdf_extractor")

MAX_PAGES = 12
_MIN_READABLE_CHARS = 80


class PDFExtractionError(Exception):
    """Raised when a PDF cannot be read or contains no usable text."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


try:
    import pymupdf as fitz  # canonical import for PyMuPDF >= 1.24
except ImportError:
    try:
        import fitz  # older PyMuPDF versions
    except ImportError:  # pragma: no cover
        fitz = None


def clean_resume_text(raw: str) -> str:
    """Normalise line endings/spacing so downstream matching is stable."""
    if not raw:
        return ""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    # Drop control characters except newline/tab.
    text = "".join(ch for ch in text if ch in ("\n", "\t") or ord(ch) >= 32)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Return cleaned, human-readable text from PDF bytes."""
    if not pdf_bytes:
        raise PDFExtractionError(
            "The uploaded file is empty. Please choose a valid PDF resume."
        )
    if not pdf_bytes.startswith(b"%PDF"):
        raise PDFExtractionError(
            "That file does not look like a valid PDF. Please upload a real .pdf resume."
        )
    if fitz is None:  # pragma: no cover
        raise PDFExtractionError(
            "PDF support is not installed on the server. Run: pip install PyMuPDF"
        )

    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            if doc.page_count == 0:
                raise PDFExtractionError("The PDF has no readable pages.")
            pages = min(doc.page_count, MAX_PAGES)
            parts = [doc.load_page(i).get_text("text") for i in range(pages)]
            raw = "\n".join(parts)
    except PDFExtractionError:
        raise
    except Exception:
        logger.exception("PDF parsing failed")
        raise PDFExtractionError(
            "The PDF could not be read. It may be corrupted — please try "
            "re-saving or re-exporting it as a PDF."
        )

    cleaned = clean_resume_text(raw)
    if len(re.sub(r"\s", "", cleaned)) < _MIN_READABLE_CHARS:
        raise PDFExtractionError(
            "No readable text could be extracted from the PDF. It may be a "
            "scanned/image-only resume — please upload a text-based PDF."
        )
    return cleaned
