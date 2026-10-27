# Upload your first document

You will create a case, upload an invoice, and read the decision. It takes about two minutes once the service is running (see [Setup](../../developer-guide/setup.md)).

## 1. Create a case

A case groups the documents of one SME's onboarding.

```bash
curl -s -X POST http://127.0.0.1:8000/v1alpha1/cases
# {"case_id":"575764f5-..."}
```

## 2. Upload a document

Send a PDF or an image (PNG, JPG, TIFF). The call returns at once; processing continues in the background.

```bash
curl -s -X POST -F "file=@assets/Examples/invoice_clean.pdf" \
  http://127.0.0.1:8000/v1alpha1/cases/<case_id>/documents
# {"document_id":"cba2934a-...","duplicate":false,"status":"processing","status_url":"/v1alpha1/documents/cba2934a-..."}
```

## 3. Read the result

Poll the status until it is no longer `processing`. With the free NVIDIA tier this can take a few minutes.

```bash
curl -s http://127.0.0.1:8000/v1alpha1/documents/<document_id>
```

```json
{
  "status": "accepted",
  "document_type": "invoice",
  "classification_confidence": 0.99,
  "reason": null,
  "facts": {"vendor_name": "Nile Supplies Co.", "invoice_number": "INV-204", "total": "1140", "currency": "EGP"},
  "evidence": [{"field": "total", "quote": "Total 1140.00", "page": 1}]
}
```

Every important fact comes with a quote from the document and its page, so a person can verify it.

## 4. Try the other outcomes

Upload `assets/Examples/invoice_wrong_total.pdf` to see a **rejected** document, or `assets/Examples/not_a_document.txt` to see one sent to **manual review**. The next page explains each outcome.

You can also run the whole flow in [Bruno](https://www.usebruno.com/): open the `bruno/` folder and run the numbered requests in order.
