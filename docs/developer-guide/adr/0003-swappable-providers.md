# ADR 0003: Swappable Storage, Parsers and LLM Providers

- Status: Accepted
- Date: 2026-10-27

## Context

The risky, fast-changing parts of the system are the object store, the document parser library and the LLM provider. The service must run end to end for anyone who clones it, and it must be possible to change any of the three without touching domain or application code.

## Decision

Each capability sits behind a provider module in `utils/providers/` that is initialised once and chosen by configuration:

- **Storage:** `storage_backend` is `local` (default) or `s3`. Stored URIs carry their scheme (`local://`, `s3://`).
- **LLM:** `llm_model` is a spec string. `nim:<model>` uses NVIDIA NIM through its OpenAI-compatible API (the default), `openai-compatible:<model>` uses any compatible server, and any other value is a native Pydantic AI model string. Structured output defaults to prompted mode, which the default NIM model needs.

## Consequences

- A reviewer can run the service with no Docker and no model download by using the local store, a fake or a hosted model key.
- Switching storage backend does not migrate existing blobs.
- NIM's tool-output mode splits answers across parallel calls with the default model, so prompted mode is the default.
- NIM-specific constrained decoding is not relied upon.
