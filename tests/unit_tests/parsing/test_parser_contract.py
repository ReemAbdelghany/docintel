"""One contract suite, run against every parser adapter."""

from pathlib import Path

import pytest

from docintel.config import Settings
from docintel.models.errors import CorruptDocument, UnsupportedFormat
from docintel.shared.ports import DocumentParser
from docintel.utils.providers.parsing import PlainTextParser, make_parser

SAMPLE = Path(__file__).resolve().parents[3] / "assets" / "Examples" / "invoice_clean.pdf"


def make(name: str) -> DocumentParser:
    if name == "plain":
        return PlainTextParser()
    if name == "unstructured":
        pytest.importorskip("unstructured")  # optional extra
    return make_parser(
        Settings(_env_file=None, llm_model="x", classifier_model="x", parser_backend=name)  # type: ignore[arg-type]
    )


@pytest.fixture(
    params=[
        "plain",
        pytest.param("docling", marks=pytest.mark.integration),
        pytest.param("unstructured", marks=pytest.mark.integration),
    ]
)
def parser_name(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def sample_for(name: str) -> tuple[bytes, str]:
    if name == "plain":
        return b"Total 1150.00\x0cSecond page", "invoice.txt"
    return SAMPLE.read_bytes(), SAMPLE.name


async def test_pages_are_numbered_from_one(parser_name: str) -> None:
    parsed = await make(parser_name).parse(*sample_for(parser_name))

    assert parsed.pages[0].number == 1
    assert "1140.00" in parsed.numbered_text() or "1150.00" in parsed.numbered_text()


async def test_garbage_raises_corrupt_document(parser_name: str) -> None:
    filename = "bad.txt" if parser_name == "plain" else "bad.pdf"
    content = b"\xff\xfe\x00" if parser_name == "plain" else b"not a document"

    with pytest.raises(CorruptDocument):
        await make(parser_name).parse(content, filename)


async def test_unknown_extension_is_unsupported(parser_name: str) -> None:
    with pytest.raises(UnsupportedFormat):
        await make(parser_name).parse(b"x", "file.xyz")


async def test_plain_text_pages_split_on_form_feed() -> None:
    parsed = await PlainTextParser().parse(b"one\x0ctwo", "a.txt")

    assert [p.number for p in parsed.pages] == [1, 2]
