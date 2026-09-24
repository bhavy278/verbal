"""Verbal — FastAPI application entrypoint.

Wires the domain HTTP API and the Phase 2 voice gateway, installs a domain-error
handler, and seeds the catalog + indexes on startup.
"""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pathlib import Path
from starlette.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from verbal.api.routes import router as api_router  # noqa: E402
from verbal.catalog.loader import seed_catalog  # noqa: E402
from verbal.db import ensure_indexes, get_client  # noqa: E402
from verbal.errors import VerbalError  # noqa: E402
from verbal.voice.gateway import router as voice_router  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("verbal")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_indexes()
    try:
        catalog = await seed_catalog()
        logger.info("Catalog seeded: %s (%d items)", catalog.id, len(catalog.items))
    except Exception:  # noqa: BLE001
        logger.exception("Catalog seed failed")
    yield
    get_client().close()


app = FastAPI(title="Verbal — AI Voice Phone Ordering Agent", version="0.2.0", lifespan=lifespan)


@app.exception_handler(VerbalError)
async def verbal_error_handler(request: Request, exc: VerbalError):
    return JSONResponse(status_code=exc.http_status, content=exc.as_dict())


app.include_router(api_router)
app.include_router(voice_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
