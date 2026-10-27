"""Manual run against a real provider: parse, classify, extract, verify. Never part of CI.

uv run python scripts/try_extract.py assets/Examples/invoice_clean.pdf
"""

import argparse
import asyncio
import time
from dataclasses import asdict
from pathlib import Path

from docintel.config import Settings
from docintel.models.rules import InvoiceRules, ReviewPolicy
from docintel.models.services import GroundingVerifier
from docintel.models.values import Confidence, DocumentType
from docintel.utils.providers.llm import make_llm_components
from docintel.utils.providers.parsing import make_parser


class _NoTelemetry:
    def stage(self, name: str, **attrs: str) -> object:
        raise NotImplementedError

    def llm_usage(self, model: str, input_tokens: int, output_tokens: int) -> None:
        pass

    def outcome(self, doc_type: str, status: str) -> None:
        pass


async def main(path: Path, output_mode: str | None) -> None:
    settings = Settings()  # reads config/.env, including the provider key
    if output_mode in ("tool", "prompted"):
        settings = settings.model_copy(update={"llm_output_mode": output_mode})
    parser = make_parser(settings)
    classifier, extractors = make_llm_components(settings, _NoTelemetry())  # type: ignore[arg-type]

    content = await asyncio.to_thread(path.read_bytes)
    started = time.perf_counter()
    parsed = await parser.parse(content, path.name)
    print(f"parse     {time.perf_counter() - started:5.1f}s  ({settings.parser_backend})")

    started = time.perf_counter()
    doc_type, confidence = await classifier.classify(parsed)
    print(f"classify  {time.perf_counter() - started:5.1f}s  {doc_type} {confidence.value:.2f}")

    started = time.perf_counter()
    outcome = await extractors[DocumentType.INVOICE].extract(parsed)
    print(f"extract   {time.perf_counter() - started:5.1f}s  mode={settings.llm_output_mode}")
    print(f"tokens    in={outcome.provenance.input_tokens} out={outcome.provenance.output_tokens}")
    for key, value in asdict(outcome.facts).items():  # type: ignore[call-overload]
        print(f"  {key}: {value}")
    for ev in outcome.evidence:
        print(f"  evidence {ev.field} p{ev.page}: {ev.snippet!r}")

    findings = [
        *InvoiceRules().check(outcome.facts),
        *GroundingVerifier().verify(outcome.facts, outcome.evidence, parsed),
    ]
    decision = ReviewPolicy(Confidence(settings.min_classification_confidence)).decide(
        findings, confidence
    )
    print("decision ", "ACCEPTED" if decision.accept else f"NEEDS_REVIEW {decision.reasons}")


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("path", type=Path)
    cli.add_argument("--mode", choices=["tool", "prompted"], default=None)
    args = cli.parse_args()
    asyncio.run(main(args.path, args.mode))
