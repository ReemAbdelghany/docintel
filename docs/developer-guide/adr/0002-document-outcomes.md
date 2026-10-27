# ADR 0002: Three outcomes: accepted, rejected, needs review

- Status: Accepted
- Date: 2026-10-27

## Decision
`rejected` means the system read the document with confidence and it fails a rule. `needs_review` means the system could not be confident (parsing, classification or extraction failed or was unsure, a quote is not in the source, a required fact is missing). When both apply, `needs_review` wins, because a rule computed from unreliable numbers proves nothing.

## Consequences
A person only sees documents the system could not decide. Rejections carry the failed rule as the reason. Grounding every quote against the parsed text means a model cannot invent a value and have it accepted.
