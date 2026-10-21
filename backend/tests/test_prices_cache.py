"""The price cache: only missing days are fetched, and the last day is overwritten (live -> closing price)."""
from datetime import date

import pandas as pd
from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import PriceBar
from app.services import prices


class FakeSource:
    name = "fake"

    def __init__(self, data):
        self.data = data
        self.calls = []

    def fetch(self, tickers, start):
        self.calls.append((tuple(tickers), start))
        return {t: s[s.index >= start] for t, s in self.data.items() if t in tickers}


def test_cache_refetches_only_from_last_day_and_updates_it(client, monkeypatch):
    db = SessionLocal()
    t = "TESTCACHE.NS"
    db.execute(delete(PriceBar).where(PriceBar.ticker == t))
    db.commit()
    d1, d2, d3 = date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)

    src = FakeSource({t: pd.Series([100.0, 101.0], index=[d1, d2])})  # d2 = live price mid-day
    monkeypatch.setattr(prices, "get_source", lambda: src)
    prices._next_refresh.pop(t, None)
    prices._refresh(db, [t])

    # Next day: d2's final close is 102, and d3 is new.
    src.data = {t: pd.Series([100.0, 102.0, 103.0], index=[d1, d2, d3])}
    prices._next_refresh.pop(t, None)
    prices._refresh(db, [t])

    assert src.calls[1][1] == d2  # second fetch started from the last saved day, not from 2019
    rows = dict(db.execute(select(PriceBar.day, PriceBar.close).where(PriceBar.ticker == t)).all())
    assert rows == {d1: 100.0, d2: 102.0, d3: 103.0}
    db.close()


def test_failed_fetch_retries_soon(client, monkeypatch):
    db = SessionLocal()

    class Broken:
        def fetch(self, tickers, start):
            raise ConnectionError("Yahoo is down")

    monkeypatch.setattr(prices, "get_source", lambda: Broken())
    prices._next_refresh.pop("DOWN.NS", None)
    prices._refresh(db, ["DOWN.NS"])  # must not raise
    wait = prices._next_refresh["DOWN.NS"] - __import__("time").time()
    assert wait <= prices.RETRY_AFTER_FAILURE_SECONDS
    db.close()
