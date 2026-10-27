# ADR 0001: Process uploads in a background task, not a job queue

- Status: Accepted
- Date: 2026-10-27

## Context
Parsing and LLM calls take seconds to minutes, so an upload must return immediately and the client polls for the result. An earlier design used a Postgres job queue and a transactional outbox (five extra tables).

## Decision
Use FastAPI `BackgroundTasks`, as the other backend services in the monorepo do. State lives in one `documents` row. Transient provider failures are retried inside the task with backoff. On startup, documents still `processing` are flagged `needs_review`.

## Consequences
Far less code and two tables instead of seven. The trade-off is durability: a restart interrupts running documents, and work cannot be spread across workers. If that matters, replace the task with a queue behind the same `process_document(document_id)` function.
