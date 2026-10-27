"""Unstructured adapter: an alternative parser, installed as an optional extra."""

import asyncio
import tempfile
from collections import defaultdict
from pathlib import Path

from docintel.models.errors import CorruptDocument, UnsupportedFormat
from docintel.models.parsed import Page, ParsedDocument
from docintel.utils.providers.parsing.common import SUPPORTED


class UnstructuredParser:
    def __init__(self, strategy: str = "auto") -> None:
        self._strategy = strategy  # 'fast', 'hi_res' or 'ocr_only'; 'auto' picks

    async def parse(self, content: bytes, filename: str) -> ParsedDocument:
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED:
            raise UnsupportedFormat(suffix)
        return await asyncio.to_thread(self._parse_sync, content, suffix)

    def _parse_sync(self, content: bytes, suffix: str) -> ParsedDocument:
        from unstructured.partition.auto import partition  # lazy: optional heavy extra

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"input{suffix}"
            path.write_bytes(content)
            try:
                elements = partition(filename=str(path), strategy=self._strategy)
            except Exception as exc:  # adapter boundary again
                raise CorruptDocument(str(exc)) from exc
        pages: dict[int, list[str]] = defaultdict(list)
        for element in elements:
            if element.text:
                pages[element.metadata.page_number or 1].append(element.text)
        if not pages:
            raise CorruptDocument("no text could be extracted")
        return ParsedDocument(
            tuple(Page(n, "\n".join(parts)) for n, parts in sorted(pages.items()))
        )
