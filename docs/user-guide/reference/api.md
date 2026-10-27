# API reference

All endpoints are under `/v1alpha1`. Interactive docs are at `/docs`.

| Method and path | Purpose | Success |
| --- | --- | --- |
| `POST /cases` | Create a case | `201` `{case_id}` |
| `POST /cases/{case_id}/documents` | Upload a PDF or image (multipart field `file`) | `202` `{document_id, duplicate, status, status_url}` |
| `GET /documents/{document_id}` | Status, decision, facts and evidence | `200` document |
| `GET /cases/{case_id}/documents` | All documents of a case (testing) | `200` list |
| `POST /documents/{document_id}/reprocess` | Run the pipeline again (testing) | `202` document |
| `GET /healthz`, `GET /readyz` | Liveness, readiness (database) | `200` |

## Errors

| Code | When |
| --- | --- |
| `404` | Unknown case or document |
| `413` | File larger than `DOCINTEL_MAX_UPLOAD_BYTES` (20 MB by default) |
| `422` | Empty file, or an invalid id |
| `503` | The database is unavailable; retry after the `Retry-After` seconds |

## Document

| Field | Meaning |
| --- | --- |
| `status` | `processing`, `accepted`, `rejected`, `needs_review` |
| `document_type` | `invoice`, `contract`, `other`, or `null` before classification |
| `classification_confidence` | 0 to 1 |
| `reason` | Why it was rejected or sent to review; `null` when accepted |
| `findings` | List of `{code, message}` |
| `facts` | Extracted values (see below), or `null` |
| `evidence` | List of `{field, quote, page}`: a verbatim quote and its page |
| `model` | The model that extracted the facts |

## Facts

**Invoice:** `vendor_name`, `invoice_number`, `issue_date`, `currency`, `subtotal`, `tax`, `total`, `line_items[{description, amount}]`. Required: vendor, number, date, total.

**Contract:** `title`, `parties[]`, `effective_date`, `end_date`, `total_value`, `currency`. Required: at least two parties and the effective date.

A fact that is not in the document is `null`, never a guess.

## Finding codes

| Code | Outcome | Meaning |
| --- | --- | --- |
| `UNGROUNDED_EVIDENCE` | needs_review | A quote was not found in the document text |
| `MISSING_FACT` | needs_review | A required fact is missing |
| `MISSING_EVIDENCE` | needs_review | A required fact has no grounded quote |
| `TOTAL_MISMATCH` | rejected | Subtotal plus tax does not equal the total |
| `LINE_ITEMS_MISMATCH` | rejected | Line items do not add up to the subtotal |
| `DATE_ORDER` | rejected | A contract ends before it starts |
| `INVALID_CURRENCY` | rejected | The currency is not a 3-letter code |

If both kinds apply, `needs_review` wins: a rule computed from unreliable values proves nothing.

## Supported files

PDF, PNG, JPG, JPEG and TIFF. Images and scans are read with OCR, so accuracy depends on image quality.
