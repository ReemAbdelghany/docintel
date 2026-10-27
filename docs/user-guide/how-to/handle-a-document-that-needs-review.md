# Handle a document that needs review or was rejected

Read the `reason` and `findings` of the document first:

```bash
curl -s http://127.0.0.1:8000/v1alpha1/documents/<document_id>
```

| Status | What it means | What to do |
| --- | --- | --- |
| `rejected` | The document was read with confidence, but it is not an invoice or contract, or it breaks a rule. The `reason` names the rule. | Ask the SME for a corrected document and upload that. |
| `needs_review` with `parsing failed` | The file is unreadable, corrupt, or not a PDF or image. | Ask for a clean file. |
| `needs_review` with `classification` | The type could not be decided or the confidence was too low. | Have a person look at the file. |
| `needs_review` with `extraction failed` | The AI provider kept failing or never produced a valid answer. | Reprocess (below). |
| `needs_review` with an `UNGROUNDED_EVIDENCE` or `MISSING_*` finding | A value could not be traced to the document, or a required fact is missing. | Have a person check the document against the facts. |
| `needs_review` with `interrupted by a restart` | The service restarted while the document was processing. | Reprocess (below). |

## Reprocess a document

After a provider outage or a restart, run the pipeline again on the stored file:

```bash
curl -s -X POST http://127.0.0.1:8000/v1alpha1/documents/<document_id>/reprocess
```

The status goes back to `processing`. Poll it as usual.

## Uploading the same file twice

The same bytes in the same case return the existing document (`"duplicate": true`) and do not start new processing. Use reprocess instead.
