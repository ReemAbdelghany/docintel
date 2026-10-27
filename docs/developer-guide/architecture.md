# Architecture

A small FastAPI service that turns uploaded business documents (PDFs and images of contracts and invoices) into verified, structured data. It never guesses: a wrong number is worse than a missing one, so doubtful documents go to a person.

## Flow

```text
POST /v1alpha1/cases/{id}/documents
  -> store the file (local disk or S3), insert a `documents` row (status: processing), return 202
  -> background task:
       parse      Docling: PDF or image -> text per page (OCR for scans and photos)
       classify   LLM: invoice | contract | other, with a confidence
       extract    LLM: typed facts + a verbatim quote for each important fact
       verify     grounding (is the quote really in the document?), required facts, business rules
       decide     accepted | rejected | needs_review
GET /v1alpha1/documents/{id}   -> status, decision, reason, findings, facts, evidence
```

## Decisions

| Outcome | When |
| --- | --- |
| `accepted` | Classified with confidence, required facts present and grounded, business rules pass |
| `rejected` | Read with confidence, but it is not an invoice or contract, or it breaks a business rule (total does not match subtotal plus tax, line items do not add up, contract ends before it starts, bad currency) |
| `needs_review` | The system cannot be confident: parsing failed, classification failed or was below the confidence threshold, extraction failed after retries, a quote is not in the document, or a required fact is missing |
| `processing` | Still running. A restart flags unfinished documents as `needs_review`; reprocess them. |

## Layout (the standard Python backend layout)

```text
src/docintel/
  main.py, config.py               app, lifespan, settings
  models/document.py               SQLModel tables: cases, documents
  shared/                          enums, parsed page type, processing errors
  routers/v1alpha1/
    router.py                      the endpoints
    schemas/document.py            Pydantic: API responses and the model's structured output
    components/
      crud.py                      database access
      rules.py                     grounding, required facts, business rules (no model calls)
      document_processor.py        the pipeline and the decision
  utils/
    providers/                     pg_database, storage (local/S3), parser (Docling), llm (Pydantic AI)
    common/                        retry with backoff, prompts, logging
alembic/docintel/                  migrations
bruno/                             API collection, numbered in flow order
```

Providers follow one pattern: `initialize_x()` runs once in the app lifespan and `get_x()` returns the instance.

## Swappable by configuration

| Capability | Setting | Options |
| --- | --- | --- |
| Storage | `DOCINTEL_STORAGE_BACKEND` | `local` (default), `s3` (MinIO or AWS) |
| LLM | `DOCINTEL_LLM_MODEL`, `DOCINTEL_CLASSIFIER_MODEL` | `nim:<model>` (NVIDIA NIM, default), `openai-compatible:<model>`, or any Pydantic AI model string such as `anthropic:<model>` |
| Output mode | `DOCINTEL_LLM_OUTPUT_MODE` | `prompted` (default), `tool` |

## Error handling and resilience

- Provider calls retry rate limits (429), 5xx and network errors with exponential backoff and jitter (`DOCINTEL_LLM_MAX_ATTEMPTS`, default 8). Other provider errors do not retry.
- Every processing error ends in `needs_review` with a readable reason. A document is never left in `processing` by an exception.
- A database outage returns `503` with `Retry-After`, and `/readyz` reports it.
- Uploads are content-addressed: the same bytes in the same case return the existing document.

## Security and privacy

- Document text is passed to the model as data inside `<document>` tags, with instructions to ignore any request inside it. The model has no tools, and its output is typed and validated, then grounded against the source text.
- Logs carry ids and outcomes, never document content.
- Secrets live in `config/.env` (git-ignored).

## Limitations

- Processing runs in the API process (FastAPI background tasks). A restart interrupts running documents; they are flagged for review. A durable queue (see ADR 0001) is the next step when volume or reliability needs it.
- No authentication, no review UI, no webhooks to downstream systems.
- Only invoices and contracts. Adding a type means a facts schema, a prompt, rules and one registry line in `llm_provider.py`.
- OCR quality bounds image accuracy (a sample invoice image had a vendor name read as "Supplies Nile Co.").
