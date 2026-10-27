"""The parser's output as a domain value."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Page:
    number: int
    text: str


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    pages: tuple[Page, ...]

    def page(self, number: int) -> Page | None:
        return next((p for p in self.pages if p.number == number), None)

    def numbered_text(self) -> str:
        return "\n\n".join(f"[page {p.number}]\n{p.text}" for p in self.pages)
