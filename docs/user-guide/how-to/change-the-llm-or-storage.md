# Change the LLM or the storage

Both are chosen in `config/.env`. Restart the service after changing them.

## LLM

```bash
# NVIDIA NIM (default), a free key from build.nvidia.com
DOCINTEL_LLM_MODEL=nim:nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
DOCINTEL_CLASSIFIER_MODEL=nim:nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
DOCINTEL_NVIDIA_API_KEY=<your key>

# Any OpenAI-compatible server (for example a local one)
DOCINTEL_LLM_MODEL=openai-compatible:<model-name>
DOCINTEL_LLM_BASE_URL=http://localhost:11434/v1
DOCINTEL_LLM_API_KEY=<key or any value>

# A native provider string
DOCINTEL_LLM_MODEL=anthropic:<model-name>
```

## Fallback models

If the main model fails (rate limit, outage, an error response), the next model in `DOCINTEL_LLM_FALLBACKS` is tried, for the classifier and the extractor alike:

```bash
DOCINTEL_LLM_FALLBACKS=nim:meta/llama-3.2-11b-vision-instruct,anthropic:<model-name>
```

The logs show which model answered each call (`llm_call`). Only list models that accept text and can return JSON. Image-only OCR models such as `nvidia/nemotron-parse` reject text input, and one that answers with invalid output would stop the chain instead of passing on to the next model. Retries with backoff start only when every model in the chain has failed.

Not every listed model is enabled for every account. Test a model with a few of your own documents before relying on it. If a model supports tool calling reliably you can set `DOCINTEL_LLM_OUTPUT_MODE=tool`; the default `prompted` works with the default model.

## Storage

```bash
DOCINTEL_STORAGE_BACKEND=local     # default: files under ./storage
DOCINTEL_STORAGE_BACKEND=s3        # MinIO or AWS S3
DOCINTEL_S3_ENDPOINT=http://localhost:9000
DOCINTEL_S3_BUCKET=documents
```

For MinIO start it with `docker compose -f docker/docker-compose.yml up -d minio`, then create the bucket (the script reads the standard AWS variables from your shell):

```bash
AWS_ACCESS_KEY_ID=minio AWS_SECRET_ACCESS_KEY=minio12345 uv run python scripts/init_storage.py
```

The service needs the same two variables when `DOCINTEL_STORAGE_BACKEND=s3`. Changing the backend does not move files that are already stored.
