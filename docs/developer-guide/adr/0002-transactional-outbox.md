# ADR 0002: Transactional Outbox

- Status: Accepted
- Date: 2026-10-27

## Context

Publishing after a database commit can lose events if the process exits between the commit and the publish. Publishing before commit can expose state that later rolls back.

## Decision

Persist domain events and integration events to an outbox in the same transaction as the state change. A relay dispatches pending rows at least once. Consumers and handlers must be idempotent.

## Consequences

State and event intent are atomic, while delivery is eventually consistent. Duplicate delivery is expected and handled with stable idempotency keys. A poisoned event is retried and eventually parked for inspection.
