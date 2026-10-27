"""Document parsing using Docling.

This module provides document parsing capabilities using the Docling library,
which handles PDF and image files (including OCR for scanned documents and photos).
The parser extracts text content per page, preserving page numbers for evidence
grounding in downstream extraction and verification steps.

Supported file formats: PDF, PNG, JPG, JPEG, TIFF.

The Docling converter is initialized once at startup and reused for all parsing
operations. Parsing is CPU-intensive, so the synchronous conversion runs in a
thread pool to avoid blocking the event loop.
"""

import asyncio
import logging
import tempfile
from collections import defaultdict
from pathlib import Path

from docling.document_converter import DocumentConverter
from docling_core.types.doc.document import TableItem  # type: ignore[attr-defined]

from docintel.shared.document_types import ParsedPage
from docintel.shared.errors import ParseError, UnsupportedFileType

logger = logging.getLogger(__name__)

# Supported file extensions for parsing
SUPPORTED_EXTENSIONS = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".tiff"})

# Global Docling converter instance (initialized once at startup)
_converter: DocumentConverter | None = None


def initialize_parser() -> None:
    """Initialize the Docling document converter.

    Creates the global DocumentConverter instance which loads layout analysis
    and table structure recognition models. This is a one-time initialization
    that should happen at application startup.

    The function is idempotent - calling it multiple times will not re-initialize
    the converter. It is called automatically by `parse_document()` on first use
    if not already initialized.
    """
    global _converter
    if _converter is None:
        logger.info("Initializing document parser")
        _converter = DocumentConverter()


def _parse_sync(content: bytes, suffix: str) -> list[ParsedPage]:
    """Synchronously parse document content into per-page text.

    This is the internal synchronous parsing function that runs in a thread pool.
    It writes the content to a temporary file, uses Docling to convert it, and
    extracts text content grouped by page number.

    Args:
        content: Raw document bytes.
        suffix: File extension (including dot, e.g., ".pdf") for Docling to
            determine the appropriate parser.

    Returns:
        list[ParsedPage]: List of parsed pages with page numbers and text content,
            sorted by page number.

    Raises:
        ParseError: If Docling fails to convert the document or no text can be
            extracted from any page.
    """
    initialize_parser()
    assert _converter is not None  # noqa: S101 - set by initialize_parser
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"input{suffix}"  # never trust the uploaded file name
        path.write_bytes(content)
        try:
            document = _converter.convert(path).document
        except Exception as exc:  # adapter boundary: whatever the library raises is a ParseError
            raise ParseError(str(exc)) from exc
    pages: dict[int, list[str]] = defaultdict(list)
    for item, _level in document.iterate_items():
        provenance = getattr(item, "prov", None)
        if not provenance:
            continue
        text = (
            item.export_to_markdown(doc=document)
            if isinstance(item, TableItem)
            else getattr(item, "text", "")
        )
        if text:
            pages[provenance[0].page_no].append(text)
    if not pages:
        raise ParseError("no text could be extracted")
    return [ParsedPage(number, "\n".join(parts)) for number, parts in sorted(pages.items())]


async def parse_document(content: bytes, filename: str) -> list[ParsedPage]:
    """Parse a document asynchronously, returning per-page text.

    Validates the file extension against supported formats, then delegates to
    the synchronous parser running in a thread pool to avoid blocking the event
    loop.

    Args:
        content: Raw document bytes.
        filename: Original filename (used only for extension detection).

    Returns:
        list[ParsedPage]: List of parsed pages with page numbers and text content,
            sorted by page number.

    Raises:
        UnsupportedFileType: If the file extension is not in the supported set
            (PDF, PNG, JPG, JPEG, TIFF).
        ParseError: If document conversion fails or no text can be extracted.
    """
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileType(f"{suffix or 'no extension'} is not a PDF or an image")
    return await asyncio.to_thread(_parse_sync, content, suffix)  # CPU-bound: keep the loop free
