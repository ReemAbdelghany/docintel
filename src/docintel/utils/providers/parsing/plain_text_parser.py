"""A key-free, model-free parser for tests: one page per form feed."""

from pathlib import Path

from docintel.models.errors import CorruptDocument, UnsupportedFormat
from docintel.models.parsed import Page, ParsedDocument


class PlainTextParser:
    async def parse(self, content: bytes, filename: str) -> ParsedDocument:
        if Path(filename).suffix.lower() != ".txt":
            raise UnsupportedFormat(Path(filename).suffix)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CorruptDocument(str(exc)) from exc
        pages = tuple(Page(n, p) for n, p in enumerate(text.split("\f"), start=1) if p.strip())
        if not pages:
            raise CorruptDocument("no text could be extracted")
        return ParsedDocument(pages)
