"""Manual run: parse a file with the chosen parser and print each page.

uv run python scripts/try_parse.py assets/Examples/invoice_clean.pdf --parser docling
"""

import argparse
import asyncio
import time
from pathlib import Path
from typing import Literal, cast

from docintel.config import Settings
from docintel.utils.providers.parsing import make_parser


async def main(path: Path, backend: str) -> None:
    settings = Settings(
        _env_file=None,
        llm_model="unused",
        classifier_model="unused",
        parser_backend=cast(Literal["docling", "unstructured"], backend),
    )
    parser = make_parser(settings)
    started = time.perf_counter()
    content = await asyncio.to_thread(path.read_bytes)
    parsed = await parser.parse(content, path.name)
    print(f"parsed in {time.perf_counter() - started:.1f}s with {backend}")
    for page in parsed.pages:
        print(f"--- page {page.number} ---\n{page.text[:200]}")


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("path", type=Path)
    cli.add_argument("--parser", default="docling", choices=["docling", "unstructured"])
    args = cli.parse_args()
    asyncio.run(main(args.path, args.parser))
