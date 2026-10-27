"""Parser adapters behind the DocumentParser port, chosen by settings."""

from docintel.config import Settings
from docintel.shared.ports import DocumentParser
from docintel.utils.providers.parsing.docling_parser import DoclingParser
from docintel.utils.providers.parsing.plain_text_parser import PlainTextParser
from docintel.utils.providers.parsing.unstructured_parser import UnstructuredParser


def make_parser(settings: Settings) -> DocumentParser:
    match settings.parser_backend:
        case "docling":
            return DoclingParser()
        case "unstructured":
            return UnstructuredParser(settings.unstructured_strategy)


__all__ = ["DoclingParser", "PlainTextParser", "UnstructuredParser", "make_parser"]
