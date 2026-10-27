"""Stable JSON form of a parsed document, so later stages and reprocessing never re-parse."""

import json

from docintel.models.parsed import Page, ParsedDocument


def serialize(parsed: ParsedDocument) -> bytes:
    return json.dumps([{"number": p.number, "text": p.text} for p in parsed.pages]).encode()


def deserialize(data: bytes) -> ParsedDocument:
    return ParsedDocument(tuple(Page(item["number"], item["text"]) for item in json.loads(data)))
