"""Docling turns a PDF or an image into text per page (OCR included for scans and photos)."""

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

SUPPORTED_EXTENSIONS = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".tiff"})

_converter: DocumentConverter | None = None


def initialize_parser() -> None:
    """Build the converter once: it loads layout and table models."""
    global _converter
    if _converter is None:
        logger.info("Initializing document parser")
        _converter = DocumentConverter()


def _parse_sync(content: bytes, suffix: str) -> list[ParsedPage]:
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
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileType(f"{suffix or 'no extension'} is not a PDF or an image")
    return await asyncio.to_thread(_parse_sync, content, suffix)  # CPU-bound: keep the loop free
