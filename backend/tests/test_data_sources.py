"""Data-source code tested with fake responses (no internet needed)."""
from datetime import date

import pandas as pd

from app.services.news import _parse_feed, tag_headline
from app.services.prices import DemoSource, YFinanceSource, to_ticker

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Infosys shares fall 4% after weak Q2 guidance - Economic Times</title>
<link>https://example.com/a</link><pubDate>Mon, 13 Oct 2025 10:00:00 GMT</pubDate>
<source url="https://economictimes.com">Economic Times</source></item>
<item><title>Infosys bags $1 billion deal from European client - Mint</title>
<link>https://example.com/b</link><source url="https://livemint.com">Mint</source></item>
</channel></rss>"""


def test_parse_feed_strips_source_and_tags():
    items = _parse_feed(RSS, 10)
    assert items[0].title == "Infosys shares fall 4% after weak Q2 guidance"
    assert items[0].source == "Economic Times"
    assert items[0].tone == "negative" and items[0].event_type == "earnings"
    assert items[0].published.startswith("2025-10-13")
    assert items[1].tone == "positive" and items[1].event_type == "deal"


def test_tag_headline():
    assert tag_headline("SEBI probe into company accounts")[1] == "regulatory"
    assert tag_headline("CEO resigns with immediate effect") == ("negative", "management")
    assert tag_headline("Company to hold AGM on Friday") == ("neutral", "general")


def test_to_ticker():
    assert to_ticker("INFY") == "INFY.NS"
    assert to_ticker("^NSEI") == "^NSEI"
    assert to_ticker("RELIANCE.BO") == "RELIANCE.BO"


def test_yfinance_source_reads_multiindex(monkeypatch):
    days = pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"])
    cols = pd.MultiIndex.from_product([["INFY.NS", "^NSEI"], ["Open", "Close"]])
    df = pd.DataFrame([[1, 100, 1, 20000], [1, 101, 1, 20100], [1, None, 1, 20200]], index=days, columns=cols)

    import yfinance

    monkeypatch.setattr(yfinance, "download", lambda *a, **k: df)
    out = YFinanceSource().fetch(["INFY.NS", "^NSEI"], date(2025, 1, 1))
    assert out["INFY.NS"].tolist() == [100, 101]  # missing day dropped
    assert out["^NSEI"].index[0] == date(2025, 1, 1)


def test_demo_source_is_repeatable():
    a = DemoSource().fetch(["INFY.NS"], date(2024, 1, 1))["INFY.NS"]
    b = DemoSource().fetch(["INFY.NS"], date(2024, 1, 1))["INFY.NS"]
    assert a.equals(b)
