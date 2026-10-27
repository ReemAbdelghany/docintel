# SME Document Intelligence Service: Architecture and Decision Guide

Every section ends with the reasoning behind the choice.

## 1. What the system does

When an SME is onboarded, it uploads a packet of documents: contracts between stakeholders, office leases, monthly expense invoices, and similar. The service turns each document into **validated, typed, auditable data** that underwriting and legal systems can consume without reading the PDF.

**In scope:** upload, parse, classify, extract, validate, human review for doubtful results, event publication to downstream systems.

**Out of scope:** the underwriting decision itself, a review UI beyond a minimal API, authentication provider integration.

**Core principle to repeat:** in underwriting, a wrong number is worse than a missing number. The design therefore prefers "flag for review" over "guess confidently".

## 2. Architectural style: Hexagonal (Ports and Adapters) with a Service Layer, using DDD concepts

This is the style described in the book *Architecture Patterns with Python* (Percival and Gregory, often called Cosmic Python), and it follows Alistair Cockburn's hexagonal architecture and Robert Martin's dependency rule.

**The rule:** dependencies point inward only.

```
  routers + utils/providers (FastAPI, worker, SQLAlchemy, Docling/Unstructured, Pydantic AI, S3/local disk)
        |  depends on
        v
  shared (use cases, unit of work, ports = Protocols)
        |  depends on
        v
  models (entities, value objects, rules; pure Python, no I/O)
```

**Why this style, in one breath:** the risky, fast-changing parts of this system are the LLM provider, the parser library, and the queue. Putting them behind interfaces means I can swap them, test everything else without them, and explain exactly where each responsibility lives.

**Enforcement:** two import-linter contracts in CI fail the build if `models` imports a framework or an outer layer, or if `shared` imports a provider or a router. An architecture that is checked by a tool is more trustworthy than one described in a README.

## 3. Domain-driven design

Strategic design splits the problem into contexts and fixes a shared language; tactical design models the core context with aggregates, value objects and domain events. The contexts are a way of thinking and naming, not separate packages: all domain code lives in `models/`, all use cases in `shared/`. DDD is applied in proportion: the core context gets the full treatment, the simple ones stay thin. This section is the source of truth for names; the rest of the document follows it.

### Subdomains and bounded contexts

| Context | Subdomain type | Responsibility | Aggregate root |
| --- | --- | --- | --- |
| Document Understanding | Core | Turn a submitted document into verified facts, each backed by evidence | `DocumentAnalysis` |
| Intake | Supporting | Receive onboarding cases and submitted documents, reject duplicates | `OnboardingCase` |
| Review | Supporting | A human confirms or corrects analyses the system doubts | `ReviewTask` |
| Parsing, LLM access, storage, queue | Generic | Commodity capabilities, kept behind adapters | none |

**Why Document Understanding is the core:** it holds the company-specific judgement (what counts as a trustworthy fact in underwriting), and its quality is what differentiates the product. Parsers, models and queues are replaceable; the rules about evidence and acceptance are not.

### Context map

| Relationship | Pattern | How it works |
| --- | --- | --- |
| Intake to Document Understanding | Customer/Supplier | Intake publishes `DocumentSubmitted`; Understanding keeps only the document id and storage reference |
| Document Understanding to Review | Customer/Supplier | `ReviewRequested` out, `ReviewResolved` back in |
| Document Understanding to underwriting and legal systems | Published Language | A versioned integration event (`document.processed.v1`) with a stable schema; consumers never see internal models |
| Document Understanding to Docling and LLM providers | Anti-corruption layer | Adapters translate vendor shapes into domain types |

**Rules:** contexts share no entities and talk only through ids and events (kept by convention and code review, grouped by file name such as `models/analysis.py`, `models/onboarding_case.py` and `models/review_task.py`). They live in one modular monolith, so they could become services later without redesign.

### Ubiquitous language

These words are the class and method names, the test names and the words used in conversation. No generic names such as `Manager`, `Helper` or `data`.

| Term | Meaning |
| --- | --- |
| Case | One SME's onboarding application |
| Submission | A file as uploaded, before anyone interprets it |
| Analysis | The system's work on one submission, from parsing to a decision |
| Extraction | The typed facts read from a document, with a schema version |
| Evidence | The page and text snippet that supports one fact |
| Finding | A rule violation or doubt about an extraction, either blocking or advisory |
| Verification | Checking facts against business rules and against the source text |
| Review | A person confirming or correcting an analysis |
| Acceptance | The decision that the facts are trusted for downstream use |

### Aggregates and invariants

**`DocumentAnalysis`** (Understanding, identity = document id) holds the status, the `DocumentType`, the current `Extraction`, its `Evidence`, the `Findings` and the decision history. It protects these invariants:

- Status moves only along allowed transitions.
- It cannot be accepted while any blocking finding exists.
- Every required fact has evidence before acceptance.
- Re-extraction creates a new extraction version; earlier versions are kept for audit.

Behaviour lives on the aggregate as methods: `record_parse`, `classify`, `record_extraction`, `verify`, `accept`, `request_review`, `apply_review_decision`, `fail`. Each method enforces its invariants and raises domain events.

**`OnboardingCase`** (Intake) owns its `SubmittedDocument` entities. Invariants: no two submissions with the same content hash in one case, and a closed case accepts no new submissions.

**`ReviewTask`** (Review). Invariants: it is resolved exactly once, a resolution carries a reviewer id, and every correction carries a reason.

**Aggregate rules:** keep aggregates small, reference other aggregates by id, change one aggregate per transaction, and let events coordinate the rest (eventual consistency inside the monolith). Use one repository per aggregate root; use cases only load, call, save and collect events.

### Value objects

Frozen, validated on construction, equal by value: `Money` (Decimal plus ISO currency), `DateRange`, `ContentHash`, `Confidence` (0 to 1), `Evidence` (page and snippet), `DocumentType`. An invalid value cannot exist, so downstream code never re-checks it. Money is never a float, dates are real dates, a missing fact is an explicit not-found rather than a default, and every extraction carries a schema version.

### Domain services and policies

- `GroundingVerifier` is a stateless domain service: it confirms each evidence snippet appears in the parsed text.
- `ReviewPolicy` uses the specification pattern to decide between auto-accept and review from findings and confidence. Thresholds are injected configuration; the rules are code.
- Per-type rules (`LeaseRules`, `InvoiceRules`, for example line items summing to the total) implement one `ExtractionRules` protocol and are looked up in the registry.

### Domain events and integration events

Domain events are internal and describe something that happened inside a context (`ExtractionCompleted`, `ReviewRequested`). The unit of work writes them to an outbox in the same transaction as the aggregate state change. A relay dispatches them at least once, so handlers must be idempotent. Integration events are public, versioned and live in `shared/contracts/` (`document.processed.v1`); they also leave the system through the outbox. Events crossing a context boundary are defined in `shared/contracts/`. Keeping internal and public contracts apart lets internal models change without breaking consumers.

### Where DDD stops

- Domain classes are plain Python dataclasses, frozen for value objects, with no framework imports. Pydantic lives at the edges: API request and response schemas in `routers/`, and the LLM output schemas in `utils/providers/llm/`. The LLM-facing schema is an external contract, and an adapter maps it into domain value objects. The cost is a mapping layer; the benefit is that prompt and schema changes never ripple into the domain.
- Intake and Review are close to CRUD. They get an aggregate and a repository, but no elaborate domain services.
- No event sourcing and no CQRS read models: the problem does not justify the cost. Status and history tables give the audit trail.

## 4. Processing pipeline

A staged pipeline (pipes and filters), orchestrated by one application service. Each stage persists its result and moves the document through a state machine, so any failure resumes from the last good stage instead of restarting.

```
RECEIVED -> PARSED -> CLASSIFIED -> EXTRACTED -> VALIDATED -> ACCEPTED
                                                     |
                                                     +-> NEEDS_REVIEW -> ACCEPTED | REJECTED
(any stage) -> FAILED   (terminal, after retries or a permanent error)
```

1. **Ingest.** API stores the file in object storage, computes a SHA-256 content hash, creates the `Document` row, enqueues a job, returns `202 Accepted`. Same hash within the same case returns the existing document (idempotency).
2. **Parse.** Docling converts the file to a structured document (text with page numbers, tables, reading order, OCR for scans). Output is stored so later stages and reprocessing do not re-parse.
3. **Classify.** A small, cheap model assigns a document type (`lease`, `invoice`, `contract`, `other`) with a confidence value.
4. **Extract.** A type-specific Pydantic AI agent returns a typed schema, with a supporting text snippet and page for each important field.
5. **Validate.** Deterministic code checks the result (dates ordered, line items sum to the total, currency valid, required fields present). A grounding check confirms each cited snippet actually appears in the parsed text.
6. **Decide.** Clean results are accepted. Anything with failed rules, low confidence, or ungrounded values goes to `NEEDS_REVIEW`.
7. **Publish.** A `document.processed` event is written to an outbox table in the same transaction as the result, then relayed to downstream systems.

**Where the stages live:** ingest belongs to Intake; parse, classify, extract, verify and decide belong to Document Understanding; the review step belongs to Review. Stages hand over through domain events, so each context can be tested alone.

**Why a fixed pipeline and not a "multi-agent swarm":** the steps are known in advance, so a deterministic pipeline is cheaper, testable, and debuggable. LLM agents appear only where judgment is needed (classify, extract). Retries cover schema and format errors only; business-rule failures become findings and route the complete extraction to review rather than discarding it by asking the model to retry.

**Why classify first, then extract:** small schemas per document type are more accurate, cheaper, and independently measurable than one giant prompt. It also makes adding a document type a local change.

## 5. Project layout

The repository root is the project root. The layout is the standard Python backend template; the architecture above maps onto it as shown.

```text
alembic/docintel/            # alembic.ini + migrations/ (env.py, versions/)
assets/
  Examples/                  # synthetic golden documents for evals and demos
  Templates/                 # prompt and report templates
config/                      # .env (git-ignored) and .env.example
docker/                      # Dockerfile, docker-compose.yml, commands.md
docs/
  developer-guide/           # architecture.md, setup.md, adr/, explanation/
  user-guide/                # how-to/, reference/, tutorials/
notebooks/  scripts/         # scripts/check.sh, up.sh, down.sh
src/docintel/
  main.py                    # FastAPI app
  config.py                  # pydantic-settings
  bootstrap.py               # composition root: wires providers into use cases
  worker.py                  # job worker and outbox relay entry point
  models/                    # DOMAIN, framework-free dataclasses
    analysis.py              # DocumentAnalysis aggregate root
    onboarding_case.py       # OnboardingCase aggregate
    review_task.py           # ReviewTask aggregate
    values.py                # Money, DateRange, Evidence, Confidence, DocumentType
    facts/                   # LeaseFacts, InvoiceFacts, ContractFacts
    rules/                   # per-type ExtractionRules, ReviewPolicy
    services.py              # GroundingVerifier
    events.py                # domain events
    errors.py                # DomainError, TransientError, PermanentError
  shared/                    # APPLICATION layer
    ports.py                 # DocumentParser, Classifier, Extractor, BlobStore, JobQueue, EventPublisher, UnitOfWork
    repositories.py          # repository Protocols, one per aggregate root
    use_cases/               # submit_document, process_document, apply_review_decision, resolve_review, reprocess
    registry.py              # doc type -> (facts, extractor, rules)
    messaging.py             # worker loop and handler table (SQL lives in providers/queue)
    contracts/               # published language: versioned integration events
  routers/                   # API
    router.py                # mounts the versioned routers
    schemas/                 # shared DTOs (problem-details)
    v1alpha1/components/     # cases.py, documents.py, reviews.py, health.py
    v1alpha1/schemas/        # request and response schemas
  utils/
    common/                  # ids, clock, hashing
    image_processing/        # scan and page preprocessing for OCR
    providers/               # ADAPTERS
      parsing/               # DoclingParser, UnstructuredParser (+ a plain-text fake)
      llm/                   # Pydantic AI agents, LLM schemas, mappers (ACL)
      db/                    # SQLAlchemy tables, repositories, unit of work
      storage/               # S3-compatible and local-disk BlobStore
      queue/                 # Postgres job queue and outbox relay
    tracking/                # logging, tracing, metrics setup
tests/
  unit_tests/                # domain and use cases with in-memory fakes
  api_tests/automated/       # API and integration tests (real Postgres, MinIO)
  backtesting/               # golden-set eval runner and reports
  stress_tests/
```

**Why a composition root (`bootstrap.py`, at the package root):** it is the only file that knows which concrete classes are used, which is why it cannot live in `shared/`, whose contract forbids importing providers. Everything else receives dependencies through constructors or FastAPI `Depends`. That is conventional dependency injection in Python without a framework.

## 6. Ports and adapters

Each port is a `typing.Protocol` defined in `shared/ports.py`; its implementation lives in `utils/providers/`.

- **DocumentParser** -> `DoclingParser` (default) or `UnstructuredParser`, chosen by `parser_backend`. Two real adapters prove the abstraction, and one contract-test suite runs against both. Both run locally, which matters for sensitive financial documents.
- **Classifier / Extractor** -> Pydantic AI agents. Model is chosen by a configuration string (`nim:<model>` for NVIDIA NIM, `openai-compatible:<model>` for any compatible server, or a native Pydantic AI string such as `anthropic:<model>`), so providers swap without code changes. Use a fallback model for provider outages and a concurrency limit per provider.
- **BlobStore** -> S3-compatible (MinIO locally) or local disk, chosen by `storage_backend`; stored URIs carry their scheme.
- **JobQueue** -> Postgres `jobs` table claimed with `FOR UPDATE SKIP LOCKED`; enqueueing can share the transaction that changes aggregate state.
- **EventPublisher** -> the outbox relay target (webhook or stream).
- **UnitOfWork** -> SQLAlchemy session per use case, committing results and outbox events atomically.

**What to say about Pydantic AI:** it gives typed outputs validated by Pydantic, dependency injection through a run context, OpenTelemetry instrumentation, a built-in test model for key-free unit tests, and a model-agnostic API. I use it behind a port, so it is an implementation detail, not a dependency of the domain.

## 7. Cross-cutting concerns

### Configuration

`pydantic-settings`, environment-driven, one `Settings` object created in the composition root, secrets never in code. This follows the twelve-factor app convention.

### Logging

Structured JSON logs via `structlog`. Context variables bind `correlation_id`, `case_id`, `document_id`, and `stage` for every line. **Never log document content or extracted personal data**; log identifiers, sizes, durations, and error codes. Log level and format come from configuration.

### Error handling

A small exception hierarchy in the domain:

- `TransientError` (provider rate limit or timeout, storage unavailable): retried with backoff and jitter, up to a limit, then the document goes to `FAILED` with the reason.
- `PermanentError` (corrupt file, unsupported format, password-protected PDF, extraction schema retries exhausted): no retry. Unsupported or corrupt files go to `FAILED`; unreliable extractions go to `NEEDS_REVIEW`. Failed documents also appear in the review queue so a person can see and resolve them.
- The API maps errors to RFC 9457 problem-details responses with a stable error code, so clients never parse messages.
- No bare `except`; exceptions are caught at one boundary per process type (API handler, worker wrapper) and recorded on the document.

### Observability

- **Traces:** OpenTelemetry spans per stage, nested under one trace per document. Pydantic AI's built-in instrumentation adds spans for model calls and tool calls, with token usage.
- **Metrics:** documents processed by type and outcome, stage duration histograms, LLM tokens and estimated cost per document, review rate, queue depth, retry counts.
- **Health:** `/healthz` (liveness) and `/readyz` (checks database, queue, storage).
- **Demo artifact:** generate an AgentCanvas report (it reads traces from Logfire, so run it on a synthetic document) and include it in the repo, so anyone can see the flow and cost without running anything.
- **SLO to state:** fast turnaround matters after sign-up, so define a target such as "95 percent of documents processed within X seconds, a full packet within Y minutes" and show the dashboard panel for it. Pick numbers from your own measurements and label them as initial targets.

### Security and privacy

- Documents are untrusted input. **Prompt injection** is a real risk: a contract could contain text that tells the model to change its answer. Mitigations: document text is passed as data, never as instructions; extraction agents have no side-effecting tools; outputs are typed and validated; grounding checks catch values not present in the source.
- Encryption at rest for blob storage and database; signed, expiring URLs for downloads; every query scoped by tenant; reviewer actions audited.
- Retention and deletion policy documented. Data residency requirements for the countries involved should be checked with the company; flag it as an open item rather than asserting a rule.

### Scaling

- API is stateless: scale horizontally behind a load balancer.
- Workers scale horizontally. **Separate queues for parsing and for LLM work**, because they have different bottlenecks (CPU or GPU versus provider rate limits).
- Per-provider concurrency limits and backoff protect against rate limiting; the queue absorbs bursts (backpressure).
- Cache by content hash so identical files are never processed twice.
- **What changes at 100x volume** (put this in the README): run Docling as its own service with autoscaled workers, use provider batch APIs for non-urgent documents, partition the queue by tenant for fairness, move large JSON results to object storage with a pointer in the database.

## 8. Data model (Postgres)

- `onboarding_cases`, `documents` (unique on case id + content hash), `parsed_documents` (or blob pointer), `extraction_results` (JSONB data, schema version, model, prompt version, cost), `field_evidence`, `validation_issues`, `review_tasks`, `outbox_events`.
- Alembic migrations; SQLAlchemy 2.0 style with async sessions.
- **Why Postgres with JSONB:** relational integrity for workflow state, flexible storage for per-type extraction payloads, one operational dependency instead of two databases.

## 9. API surface

- All routes are versioned under `/v1alpha1` (`routers/v1alpha1/`); a breaking change gets a new version directory.
- `POST /cases` create an onboarding case.
- `POST /cases/{id}/documents` upload; returns `202` and the document id.
- `GET /documents/{id}` status, type, issues.
- `GET /documents/{id}/result` extracted data with evidence.
- `GET /reviews?status=open` includes both `NEEDS_REVIEW` and `FAILED` documents; `POST /reviews/{id}/resolve` records a decision or correction.
- `POST /documents/{id}/reprocess` re-run after a schema, prompt, or model change.
- `/healthz`, `/readyz`, `/metrics` if exposing Prometheus format.
- Consistent pagination; problem-details errors.

## 10. Testing strategy

- **Unit (fast, no I/O, `tests/unit_tests/`):** domain rules, state machine, validators, money and date handling.
- **Application tests with fakes:** in-memory repositories and unit of work, a fake parser, and Pydantic AI's test model. These exercise the full pipeline in milliseconds, including failure paths (transient error retried, permanent error recorded).
- **Integration (`tests/api_tests/automated/`, marker `integration`):** real Postgres and storage via containers; adapter contract tests (the same test suite runs against both parser adapters).
- **Evals (`tests/backtesting/`, documents in `assets/Examples/`):** a small golden set of anonymized or synthetic documents with expected fields; a runner reports field-level accuracy, grounding rate, and review rate. Run on prompt or model changes, and show the numbers in the README.
- **CI gates:** ruff (lint and format), mypy or pyright in strict mode, import-linter, pytest with a sensible coverage floor, dependency audit.

## 11. Tooling and delivery

`uv` for dependencies, `pyproject.toml` for everything, pre-commit hooks, multi-stage Dockerfile running as a non-root user, `docker/docker-compose.yml` with API, worker, Postgres, queue backend, MinIO, and an OpenTelemetry collector with a trace viewer. One script to start everything (`scripts/up.sh`), one to run all checks (`scripts/check.sh`) and one to run the demo end to end.

## 12. Decision log (turn each into a short ADR)

1. **Hexagonal modular monolith using DDD concepts, two process types.** Rejected: microservices, plain MVC.
2. **FastAPI + Pydantic v2.** Standard async Python API stack; shares the validation model with the LLM layer.
3. **SQLAlchemy 2.0 + Alembic + Postgres.** Rejected: NoSQL (workflow state needs transactions), raw SQL (testability and migrations).
4. **Repository + Unit of Work.** Rejected: active record (couples domain to ORM).
5. **Docling as default parser behind a port, with Unstructured as the second adapter.** Local execution for sensitive documents, layout and table understanding, OCR support. A second real adapter demonstrates swappability and gives the evals something to compare.
6. **Pydantic AI for LLM access.** Rejected: LangChain (heavier abstractions for a fixed pipeline), hand-rolled JSON prompting (no typed validation, fragile).
7. **Classify then extract per type.** Rejected: single universal prompt.
8. **Deterministic validators plus grounding check, with human review.** Rejected: trusting model confidence alone.
9. **Postgres-backed job queue behind a `JobQueue` port.** Jobs are claimed with `FOR UPDATE SKIP LOCKED`, and state changes plus enqueueing commit together. Rejected for the demo: another queue service and its operational burden. Keep the port so SQS or Celery can replace it at higher volume.
10. **Transactional outbox for domain and integration events.** A relay delivers at least once and handlers are idempotent. Rejected: dispatching only after commit (a process crash can lose the event).
11. **structlog + OpenTelemetry.** Vendor-neutral; backend is swappable.
12. **Single fixed pipeline, no autonomous multi-agent loop.** Predictability and auditability matter more than flexibility here.
13. **DDD with three logical contexts: Document Understanding (core), Intake and Review (supporting), kept in one flat package layout.** Rejected: one shared model for the whole system (couples every feature to every table), a service per context (no team or scaling reason yet), a package tree per context (heavier to navigate and explain than the benefit warrants here).
14. **Rich aggregates with invariants; plain dataclasses in the domain.** Rejected: anemic models with the logic in services, and Pydantic models as domain entities (couples the domain to a library and to the LLM schema).
15. **Domain and integration events are persisted to the outbox and dispatched by a relay.** Events crossing contexts live in `shared/contracts/`; external integration events are versioned. Rejected: dispatching domain events only in-process after commit (a crash can lose them), one event type for both (internal refactors would break consumers), a broker now (extra infrastructure without a need).
16. **No event sourcing and no CQRS.** Rejected for cost; status and history tables give the audit trail.
17. **Hosted NVIDIA NIM as the default LLM, through its OpenAI-compatible API.** Model strings select the provider, so Anthropic, OpenAI or a local server are one setting away. Rejected: hard-wiring one vendor SDK, and relying on NIM-specific constrained decoding that is unconfirmed on the hosted endpoint.
18. **Two blob stores, local disk and S3/MinIO, behind one port.** The local store lets anyone run the service with no containers; S3 is the production path. Stored URIs carry their scheme.

## 13. Common questions, with short answers

- **What if the model invents a number?** Grounding check against the source text, arithmetic validators and review routing. Nothing unverified is auto-accepted.
- **What if the provider is down or rate limiting?** Retry with backoff, fallback model, concurrency limits, and the queue holds work until recovery.
- **How do you know quality is good?** An eval suite with field-level accuracy tracked over time, plus review-rate metrics in production.
- **How do you control cost?** Cheap classifier, per-type schemas, content-hash caching, token and cost metrics per document.
- **How do you add a new document type?** Add facts, rules, an extractor prompt and a registry entry, then golden examples. No pipeline change.
- **What happens when the schema or model changes?** Results store schema, model and prompt versions; the reprocess endpoint re-runs documents and old results stay for comparison.
- **Why not just use a vendor's document AI?** Possible, and the port allows it as an adapter. Building this shows control over validation, evidence and cost, which underwriting needs.
- **Isn't DDD overkill here?** Only the core context uses tactical DDD; Intake and Review stay thin. The payoff is invariants that hold on every path: nothing is accepted with a blocking finding, and every required fact has evidence.
- **Why not use the LLM output models as domain objects?** They are an external contract that changes with prompts and carries no behaviour. An adapter maps them into value objects, so the domain stays stable.

## 14. Build order

1. Skeleton, domain model, state machine, ports, in-memory fakes, first tests.
2. API, Postgres, blob storage, upload and status endpoints.
3. Docling adapter and parsed-document storage.
4. Invoice extraction end to end (schema, agent, validators, grounding).
5. Queue, retries, error taxonomy, outbox and event relay.
6. Logging, tracing, metrics, health checks, dashboards, AgentCanvas report.
7. Leases and contracts, review flow.
8. Evals, README with diagram, ADRs, known limitations.

## 15. Open items to decide

- Arabic and scanned-document support: in or out of scope? It affects OCR configuration and your eval set.
- ~~LLM provider~~ Resolved: NVIDIA NIM by default (decision 17). Still to check: which hosted model gives the best field accuracy on the golden set with tool output, and whether the hosted endpoint honors `guided_json`.
- Queue implementation (decision 9).
- Whether to build a minimal review page or keep review API-only.
