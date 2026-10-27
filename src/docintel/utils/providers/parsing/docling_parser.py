"""Docling adapter: layout-aware parsing with page numbers, tables and OCR."""

import asyncio
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from docintel.models.errors import CorruptDocument, UnsupportedFormat
from docintel.models.parsed import Page, ParsedDocument
from docintel.utils.providers.parsing.common import SUPPORTED

_DOCLING_FORMATS = SUPPORTED - {".txt"}


class DoclingParser:
    def __init__(self) -> None:
        self._converter: Any = None  # built on first use: it loads models

    async def parse(self, content: bytes, filename: str) -> ParsedDocument:
        suffix = Path(filename).suffix.lower()
        if suffix not in _DOCLING_FORMATS:
            raise UnsupportedFormat(suffix)
        return await asyncio.to_thread(self._parse_sync, content, suffix)  # CPU-bound

    def _converter_once(self) -> Any:
        if self._converter is None:
            from docling.document_converter import DocumentConverter

            self._converter = DocumentConverter()
        return self._converter

    def _parse_sync(self, content: bytes, suffix: str) -> ParsedDocument:
        from docling_core.types.doc import TableItem  # type: ignore[attr-defined]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"input{suffix}"  # never trust the uploaded file name
            path.write_bytes(content)
            try:
                result = self._converter_once().convert(path)
            except Exception as exc:  # adapter boundary: translate any vendor error
                raise CorruptDocument(str(exc)) from exc
        document = result.document
        pages: dict[int, list[str]] = defaultdict(list)
        for item, _level in document.iterate_items():
            if not getattr(item, "prov", None):
                continue
            if isinstance(item, TableItem):
                text = item.export_to_markdown(doc=document)  # keeps table numbers searchable
            else:
                text = getattr(item, "text", "")
            if text:
                pages[item.prov[0].page_no].append(text)
        if not pages:
            raise CorruptDocument("no text could be extracted")
        return ParsedDocument(
            tuple(Page(n, "\n".join(parts)) for n, parts in sorted(pages.items()))
        )
