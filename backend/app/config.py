"""App settings, read from environment variables (or a .env file).

Every setting has a safe default, so the app runs locally with zero setup.
"""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Core ---
    app_name: str = "Portfolio Risk Copilot"
    # SQLite for local dev. In production use Postgres. Paste the URL your host gives you
    # (postgres://... or postgresql://...); it is converted to the right driver below.
    database_url: str = "sqlite:///./copilot.db"
    cors_origins: str = "http://localhost:5173"

    # --- Auth ---
    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24
    # Comma-separated emails that get the "admin" role on signup.
    admin_emails: str = ""

    # --- Market data ---
    # "yfinance" = real prices from Yahoo Finance.
    # "demo"     = synthetic prices (works offline, used in tests).
    price_source: str = "yfinance"
    market_index: str = "^NSEI"  # NIFTY 50
    history_start: str = "2019-01-01"  # enough history for the 2020 crash replay
    risk_free_rate: float = 0.065  # ~Indian 10Y govt bond yield, used for Sharpe
    lookback_days: int = 252  # 1 trading year for risk metrics

    # --- AI agent ---
    # Main AI: "gemini" or "groq". "offline" uses a rule-based fallback (no key needed).
    # If both keys are set, the other one is the backup: it answers when the main one fails.
    llm_provider: str = "offline"
    google_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"

    # --- Alerts ---
    enable_scheduler: bool = False
    alert_hour_ist: int = 18  # run daily after market close
    alert_minute_ist: int = 30
    daily_move_threshold_pct: float = 5.0
    drawdown_threshold_pct: float = 15.0
    concentration_threshold_pct: float = 25.0
    news_source: str = "google"  # "google" or "off"
    telegram_bot_token: str = ""
    # Secret for POST /api/cron/daily-alerts, so an outside scheduler (GitHub Actions)
    # can trigger the alert job. Empty = endpoint disabled.
    cron_secret: str = ""

    @field_validator("database_url")
    @classmethod
    def use_psycopg2_driver(cls, v: str) -> str:
        """Neon/Render give 'postgres://' or 'postgresql://'. SQLAlchemy needs 'postgresql+psycopg2://'."""
        v = v.strip()
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg2://" + v[len(prefix):]
        return v

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def admin_email_list(self) -> list[str]:
        return [e.strip().lower() for e in self.admin_emails.split(",") if e.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
