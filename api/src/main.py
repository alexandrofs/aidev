from fastapi import FastAPI
from .routes.webhooks import router as webhooks_router

app = FastAPI(title="AI Developer API", version="0.1.0")

app.include_router(webhooks_router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
