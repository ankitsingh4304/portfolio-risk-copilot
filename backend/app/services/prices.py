"""Daily closing prices, with a database cache.

Flow:  ask for prices -> check our DB -> fetch only the missing days -> save -> return.

Two sources:
  * YFinanceSource: real data from Yahoo Finance (NSE tickers end in ".NS").
  * DemoSource: realistic fake prices, so the app works offline and tests are stable.
"""
import hashlib
import logging
import threading
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import PriceBar
from . import stocks_meta

log = logging.getLogger(__name__)
settings = get_settings()

# Don't hit the data source for the same ticker more than once per this many seconds.
REFRESH_INTERVAL_SECONDS = 6 * 60 * 60
RETRY_AFTER_FAILURE_SECONDS = 10 * 60
_next_refresh: dict[str, float] = {}  # ticker -> earliest time we may fetch it again
# Requests run in parallel threads. The lock stops two requests downloading the same prices at once.
_refresh_lock = threading.Lock()
UPSERT_BATCH = 2000


def to_ticker(symbol: str) -> str:
    """'INFY' -> 'INFY.NS'. Index tickers like '^NSEI' stay as they are."""
    if symbol.startswith("^") or "." in symbol:
        return symbol
    return f"{symbol}.NS"


# ---------------------------------------------------------------- sources
class YFinanceSource:
    name = "yfinance"

    def fetch(self, tickers: list[str], start: date) -> dict[str, pd.Series]:
        import yfinance as yf

        data = yf.download(
            tickers, start=start.isoformat(), auto_adjust=True, progress=False,
            group_by="ticker", threads=True,
        )
        out: dict[str, pd.Series] = {}
        if data is None or data.empty:
            return out
        for t in tickers:
            try:
                col = data[t]["Close"] if isinstance(data.columns, pd.MultiIndex) else data["Close"]
            except KeyError:
                continue
            s = col.dropna()
            if not s.empty:
                s.index = pd.to_datetime(s.index).date
                out[t] = s.astype(float)
        return out


# Rough price levels for the sample portfolio, so demo P&L numbers look sensible.
DEMO_PRICE_HINTS = {
    "INFY": 1500, "TCS": 3100, "HDFCBANK": 950, "ICICIBANK": 1400, "RELIANCE": 1400,
    "ITC": 410, "SUNPHARMA": 1650, "BHARTIARTL": 1900, "LT": 3600, "MARUTI": 12500,
}


class DemoSource:
    """Fake but realistic prices.

    Each stock = market move x its beta + sector move + its own noise.
    The market includes a 2020 crash and a sharp fall on 4 June 2024, so the
    historical scenarios have something to replay. Same input -> same output.
    """

    name = "demo"

    @staticmethod
    def _rng(key: str) -> np.random.Generator:
        seed = int(hashlib.md5(key.encode()).hexdigest()[:8], 16)
        return np.random.default_rng(seed)

    def _days(self) -> pd.DatetimeIndex:
        return pd.bdate_range(settings.history_start, date.today())

    def _market_returns(self, days: pd.DatetimeIndex) -> np.ndarray:
        r = self._rng("MARKET").normal(0.0005, 0.009, len(days))
        crash = (days >= "2020-02-20") & (days <= "2020-03-23")
        r[crash] = r[crash] * 2.5 - 0.016  # roughly a 35-40% fall over ~5 weeks
        rebound = (days > "2020-03-23") & (days <= "2020-06-30")
        r[rebound] += 0.004
        r[days == pd.Timestamp("2024-06-04")] = -0.059
        return r

    def fetch(self, tickers: list[str], start: date) -> dict[str, pd.Series]:
        days = self._days()
        mkt = self._market_returns(days)
        out = {}
        for t in tickers:
            if t.startswith("^"):
                level = 10_800 * np.cumprod(1 + mkt)
            else:
                sym = t.split(".")[0]
                meta = stocks_meta.lookup(sym)
                sector = meta[1] if meta else "Other"
                rng = self._rng(sym)
                beta = rng.uniform(0.6, 1.35)
                idio = rng.normal(0.0, rng.uniform(0.008, 0.016), len(days))
                sector_r = self._rng("SECTOR:" + sector).normal(0, 0.006, len(days))
                hint = DEMO_PRICE_HINTS.get(sym)
                today_px = hint * rng.uniform(0.85, 1.3) if hint else rng.uniform(150, 3500)
                path = np.cumprod(1 + beta * mkt + sector_r + idio)
                level = today_px * path / path[-1]  # pin today's price so weights look sensible
            s = pd.Series(np.round(level, 2), index=days.date)
            out[t] = s[s.index >= start]
        return out


def get_source():
    return DemoSource() if settings.price_source == "demo" else YFinanceSource()


# ---------------------------------------------------------------- cache logic
def _upsert_prices(db: Session, rows: list[dict]) -> None:
    """Insert price rows. If a (ticker, day) row already exists, update its close.

    Why update? During market hours Yahoo returns today's *live* price as today's close.
    Re-fetching the last stored day and overwriting it fixes that once the market closes.
    "Upsert" in one SQL statement is also safe when two requests save the same day at once.
    """
    if not rows:
        return
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise RuntimeError(f"Unsupported database: {dialect}")
    for i in range(0, len(rows), UPSERT_BATCH):
        stmt = insert(PriceBar).values(rows[i : i + UPSERT_BATCH])
        stmt = stmt.on_conflict_do_update(index_elements=["ticker", "day"], set_={"close": stmt.excluded.close})
        db.execute(stmt)


def _refresh(db: Session, tickers: list[str]) -> None:
    """Fetch and save any days we don't have yet (plus the last saved day, in case it changed)."""
    with _refresh_lock:
        now = time.time()
        due = [t for t in tickers if now >= _next_refresh.get(t, 0)]
        if not due:
            return

        last_days = dict(
            db.execute(
                select(PriceBar.ticker, func.max(PriceBar.day))
                .where(PriceBar.ticker.in_(due))
                .group_by(PriceBar.ticker)
            ).all()
        )
        history_start = date.fromisoformat(settings.history_start)
        # Group tickers by the start date we need, so we make few calls.
        by_start: dict[date, list[str]] = {}
        for t in due:
            start = last_days.get(t) or history_start
            by_start.setdefault(start, []).append(t)

        source = get_source()
        for start, group in by_start.items():
            try:
                fetched = source.fetch(group, start)
            except Exception as exc:  # noqa: BLE001  network errors etc. Use what we have cached.
                log.warning("Price fetch failed for %s: %s", group, exc)
                fetched = {}
            rows = [
                {"ticker": t, "day": d, "close": float(px)}
                for t, series in fetched.items()
                for d, px in series.items()
                if pd.notna(px)
            ]
            _upsert_prices(db, rows)
            db.commit()
            for t in group:
                ok = t in fetched
                if not ok:
                    log.warning("No prices returned for %s", t)
                _next_refresh[t] = now + (REFRESH_INTERVAL_SECONDS if ok else RETRY_AFTER_FAILURE_SECONDS)


def get_prices(db: Session, symbols: list[str], include_market: bool = True) -> tuple[pd.DataFrame, pd.Series]:
    """Return (stock prices with one column per symbol, market index prices).

    Rows are trading days. Missing values are left as NaN (e.g. a stock that listed recently).
    """
    tickers = [to_ticker(s) for s in symbols]
    market_ticker = settings.market_index
    all_tickers = tickers + ([market_ticker] if include_market else [])
    _refresh(db, all_tickers)

    rows = db.execute(
        select(PriceBar.ticker, PriceBar.day, PriceBar.close).where(PriceBar.ticker.in_(all_tickers))
    ).all()
    if not rows:
        return pd.DataFrame(columns=symbols), pd.Series(dtype=float)

    df = pd.DataFrame(rows, columns=["ticker", "day", "close"])
    wide = df.pivot_table(index="day", columns="ticker", values="close").sort_index()
    wide.index = pd.to_datetime(wide.index)

    market = wide[market_ticker].dropna() if market_ticker in wide else pd.Series(dtype=float)
    stock_prices = pd.DataFrame(index=wide.index)
    for sym, t in zip(symbols, tickers):
        stock_prices[sym] = wide[t] if t in wide else np.nan
    return stock_prices, market


def lookup_sector_online(symbol: str) -> str | None:
    """Best-effort sector lookup from Yahoo, converted to NSE's industry names."""
    if settings.price_source == "demo":
        return None
    try:
        import yfinance as yf

        from .sectors import from_yahoo

        info = yf.Ticker(to_ticker(symbol)).info
        return from_yahoo(info.get("sector"), info.get("industry"))
    except Exception:  # noqa: BLE001
        return None
