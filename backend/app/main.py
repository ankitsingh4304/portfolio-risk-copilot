"""FastAPI app. Run locally with:  uvicorn app.main:app --reload"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import DEFAULT_JWT_SECRET, get_settings
from .database import check_db, init_db
from .routers import admin, alerts, auth, chat, cron, portfolio, scenarios
from .scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)
settings = get_settings()


def check_settings():
    """Stop the app from starting with unsafe settings on a real database."""
    weak_secret = settings.jwt_secret == DEFAULT_JWT_SECRET or len(settings.jwt_secret) < 32
    if weak_secret and not settings.is_sqlite:
        raise RuntimeError(
            "JWT_SECRET is missing or too short. Set it to a long random value (32+ characters) before "
            "running on a real database. Generate one with:  python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
    if weak_secret:
        log.warning("JWT_SECRET is the default/short value. Fine for local testing, never for deployment.")
    if settings.llm_provider == "gemini" and not settings.google_api_key:
        log.warning("LLM_PROVIDER=gemini but GOOGLE_API_KEY is empty. The Ask page will use basic mode.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_settings()
    init_db()  # runs database migrations
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title=settings.app_name,
    description="Upload your stock holdings, see your risk, run what-if scenarios, and ask an AI about it.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth.router, portfolio.router, scenarios.router, chat.router, alerts.router, admin.router, cron.router):
    app.include_router(r, prefix="/api")


@app.get("/api/health", tags=["health"])
def health():
    """Used by the host to check the app is alive. Returns 503 if the database can't be reached."""
    db_ok = check_db()
    body = {
        "status": "ok" if db_ok else "error",
        "database": "ok" if db_ok else "unreachable",
        "price_source": settings.price_source,
        "llm_provider": "gemini" if settings.llm_provider == "gemini" and settings.google_api_key else "offline",
        "scheduler": settings.enable_scheduler,
    }
    return JSONResponse(body, status_code=200 if db_ok else 503)
