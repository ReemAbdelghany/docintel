# ADR 0004: Swappable Storage, Parsers and LLM Providers

- Status: Accepted
- Date: 2026-10-27

## Context

The risky, fast-changing parts of the system are the object store, the document parser library and the LLM provider. The service must run end to end for anyone who clones it, and it must be possible to change any of the three without touching domain or application code.

## Decision

Each capability is a `Protocol` port in `shared/ports.py` with a factory in `utils/providers/` that selects the adapter from configuration:

- **Storage:** `storage_backend` is `local` (default) or `s3`. Stored URIs carry their scheme (`local://`, `s3://`).
- **Parsing:** `parser_backend` is `docling` (default) or `unstructured`. A plain-text fake supports key-free end-to-end tests.
- **LLM:** `llm_model` is a spec string. `nim:<model>` uses NVIDIA NIM through its OpenAI-compatible API (the default), `openai-compatible:<model>` uses any compatible server, and any other value is a native Pydantic AI model string. Structured output uses tool output by default, with a prompted fallback.

One contract-test suite runs against every adapter of a port. Provider accuracy is compared in the eval report.

## Consequences

- A reviewer can run the service with no Docker and no model download by using the local store, a fake or a hosted model key.
- Switching storage backend does not migrate existing blobs.
- Unstructured is an optional dependency extra; its tests skip when it is not installed.
- NIM-specific constrained decoding is not relied upon; the hosted endpoint's support is unconfirmed.
