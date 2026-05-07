"""File text extraction — used by the per-church KB ingestion pipeline (FR-09).

Given an arbitrary file path (PDF / Markdown / plain text), return its plain-
text contents suitable for chunking + embedding.

PDFs delegate to the existing `pdf_extractor.extract_text` helper so the same
extraction stack (pdfplumber → pypdf fallback) is used everywhere.

For .md and .txt we read the file directly with utf-8.
"""
from __future__ import annotations
from pathlib import Path
from typing import Union

from .pdf_extractor import extract_text as _pdf_extract


_TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".rst"}


class UnsupportedFileType(ValueError):
    """Raised when an unsupported file extension is passed to extract_text()."""


def extract_text(file_path: Union[str, Path]) -> str:
    """Return the plain-text content of a PDF / Markdown / TXT file.

    Args:
        file_path: Absolute or relative path to the file.

    Returns:
        UTF-8 text. For PDFs uses pdfplumber → pypdf. For .md / .txt, reads
        the file directly.

    Raises:
        FileNotFoundError: if the path does not exist.
        UnsupportedFileType: if the extension is not one of {.pdf,.md,.txt,.rst}.
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return _pdf_extract(str(p))
    if suffix in _TEXT_SUFFIXES:
        try:
            return p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return p.read_text(encoding="latin-1", errors="replace")
    raise UnsupportedFileType(
        f"Unsupported file type {suffix!r} (want .pdf/.md/.txt/.rst)"
    )
