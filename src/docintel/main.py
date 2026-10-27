from fastapi import FastAPI

app = FastAPI(title="SME Document Intelligence Service", version="0.1.0")


@app.get("/healthz", tags=["health"])
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
