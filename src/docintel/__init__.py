"""Document Intelligence Service package.

This package provides the SME Document Intelligence Service for onboarding
document processing. It accepts business documents (contracts, invoices),
extracts typed facts with page-level evidence, validates them deterministically,
and routes doubtful results to human review.

Main entry point: docintel.main
"""


def main() -> None:
    """Run the API server (alternative entry point).

    This allows running the service via `python -m docintel`.
    """
    import uvicorn

    uvicorn.run("docintel.main:app", host="127.0.0.1", port=8000)
