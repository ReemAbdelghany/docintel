# ADR 0003: Route Business-Rule Failures to Review

- Status: Accepted
- Date: 2026-10-27

## Context

Asking an LLM to retry after a deterministic business-rule failure can replace a useful but questionable extraction with a different answer, or exhaust retries and discard the original result.

## Decision

Use model retries only for schema and formatting errors. Run business rules and evidence grounding after extraction; represent violations as findings and send the extraction to human review.

## Consequences

Reviewers retain the model's original facts, evidence, and provenance. Permanent parsing or extraction failures are marked `FAILED` and are visible in the review queue rather than disappearing from the human workflow.
