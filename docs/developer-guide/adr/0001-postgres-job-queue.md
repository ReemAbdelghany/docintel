# ADR 0001: Postgres-Backed Job Queue

- Status: Accepted
- Date: 2026-10-27

## Context

The service needs durable asynchronous processing for parsing and LLM work. The initial demo should keep infrastructure small while making queued work visible and transactionally consistent with document state.

## Decision

Store jobs in Postgres behind the `JobQueue` port. Workers claim due jobs using `FOR UPDATE SKIP LOCKED`. Enqueueing a follow-up job can happen in the same unit of work as the aggregate transition that requires it.

## Consequences

The demo has one fewer service to operate and can inspect jobs with ordinary SQL. Postgres also carries queue load, so parsing and LLM workers need separate pools and concurrency controls. At higher volume, replace the adapter with a dedicated queue without changing use cases.
