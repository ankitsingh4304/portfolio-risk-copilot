"""Stock news from Google News RSS (free, no API key), plus simple headline tagging.

Tagging is rule-based on purpose: alerts run every day for every user, so they
should be fast, free and predictable. The AI agent can still read and summarise
the same headlines when a user asks.
"""
import logging
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from urllib.parse import quote_plus

import feedparser
import httpx

from ..config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()

CACHE_SECONDS = 30 * 60
_cache: dict[str, tuple[float, list]] = {}

NEGATIVE = r"\b(falls?|fell|slumps?|plunges?|plummets?|tanks?|crash(es)?|tumbles?|sinks?|drops?|downgrade[sd]?|" \
           r"probe|raids?|fraud|penalty|fined?|lawsuit|sued|resigns?|resignation|default(s|ed)?|layoffs?|" \
           r"recall|ban(s|ned)?|loss(es)?|misses|cuts? (target|guidance|outlook)|sell rating|warning|weak)\b"
POSITIVE = r"\b(surges?|soars?|jumps?|rall(y|ies)|gains?|climbs?|upgrade[sd]?|record|beats?|wins?|" \
           r"bags?|secures?|buy rating|raises? (target|guidance)|strong|outperform)\b"
EVENT_TYPES = {
    "earnings": r"\b(q[1-4]|results?|quarterly|earnings|profit|revenue|ebitda|margin)\b",
    "regulatory": r"\b(sebi|rbi|probe|penalty|ban|tax|raid|court|tribunal|nclt|regulator|compliance)\b",
    "management": r"\b(ceo|cfo|md|chairman|resigns?|appoint(s|ed)?|board)\b",
    "deal": r"\b(acquir(e|es|ed|ition)|merger|stake|order|contract|deal|partnership|buyback)\b",
    "rating": r"\b(upgrade|downgrade|target price|rating|brokerage|outperform|underperform)\b",
}


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    published: str | None
    tone: str  # negative | positive | neutral
    event_type: str  # earnings | regulatory | management | deal | rating | general

    def to_dict(self):
        return asdict(self)


def tag_headline(title: str) -> tuple[str, str]:
    t = title.lower()
    neg = len(re.findall(NEGATIVE, t))
    pos = len(re.findall(POSITIVE, t))
    tone = "negative" if neg > pos else "positive" if pos > neg else "neutral"
    event = next((k for k, pat in EVENT_TYPES.items() if re.search(pat, t)), "general")
    return tone, event


def _parse_feed(text: str, limit: int) -> list[NewsItem]:
    feed = feedparser.parse(text)
    items = []
    for e in feed.entries[:limit]:
        title = e.get("title", "").strip()
        source = e.get("source", {}).get("title", "") if isinstance(e.get("source"), dict) else ""
        # Google appends " - Source" to titles; keep the title clean.
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        published = None
        if e.get("published_parsed"):
            published = datetime(*e.published_parsed[:6], tzinfo=timezone.utc).isoformat()
        tone, event = tag_headline(title)
        items.append(NewsItem(title, e.get("link", ""), source, published, tone, event))
    return items


def fetch_news(company: str, symbol: str, limit: int = 8) -> list[NewsItem]:
    """Recent headlines for a company. Returns [] on any network error."""
    if settings.news_source == "off":
        return []
    key = f"{symbol}:{limit}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    query = quote_plus(f'"{company}" share OR stock when:7d')
    url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        resp = httpx.get(url, timeout=10, follow_redirects=True)
        resp.raise_for_status()
        items = _parse_feed(resp.text, limit)
    except Exception as exc:  # noqa: BLE001
        log.warning("News fetch failed for %s: %s", symbol, exc)
        return []
    _cache[key] = (time.time(), items)
    return items
