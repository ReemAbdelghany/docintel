# Settings reference

Read from environment variables with the `DOCINTEL_` prefix, or from `config/.env`.

| Setting | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://docintel:docintel@localhost:5433/docintel` | Postgres |
| `STORAGE_BACKEND` | `local` | `local` or `s3` |
| `LOCAL_STORAGE_PATH` | `<repo>/storage` | Where local files go |
| `S3_ENDPOINT`, `S3_BUCKET` | `http://localhost:9000`, `documents` | S3-compatible storage |
| `LLM_MODEL`, `CLASSIFIER_MODEL` | `nim:nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | Extraction and classification models |
| `LLM_OUTPUT_MODE` | `prompted` | `prompted` or `tool` |
| `NVIDIA_API_KEY` | empty | Key for `nim:` models |
| `LLM_BASE_URL`, `LLM_API_KEY` | empty | For `openai-compatible:` models |
| `LLM_MAX_ATTEMPTS` | `8` | Attempts for rate limits, 5xx and network errors |
| `MIN_CLASSIFICATION_CONFIDENCE` | `0.7` | Below this the document goes to review |
| `MAX_UPLOAD_BYTES` | `20971520` | Upload size limit |
| `LOG_LEVEL` | `INFO` | Log level |
