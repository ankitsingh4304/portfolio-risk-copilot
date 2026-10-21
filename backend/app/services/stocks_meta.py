"""Stock names and sectors, loaded from NSE's official file format.

Files (in app/data/):
  * nifty500.csv          NSE's official Nifty 500 list, if you've downloaded it.
                          Get it with:  python -m scripts.update_stock_list
  * nse_stocks.csv        A starter list of ~125 large NSE stocks in the same format,
                          shipped with the app so it works out of the box.
  * extra_instruments.csv ETFs and renamed companies that aren't in the Nifty 500.

The official file wins when a stock appears in more than one.
For a stock in none of the files, the upload's own sector column is used, then
Yahoo Finance, then "Other" (see routers/portfolio.py).
"""
import csv
import logging
import re
from functools import lru_cache
from pathlib import Path

from .sectors import normalize_sector

log = logging.getLogger(__name__)
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
FILES_IN_PRIORITY_ORDER = ["nifty500.csv", "nse_stocks.csv", "extra_instruments.csv"]

# "lt" covers truncated names like "TATA CONSULTANCY SERV LT".
_SUFFIXES = r"\b(limited|ltd|lt|pvt|private|corporation|corp|company|co|inc|the)\b"


def normalize_name(name: str) -> str:
    """'INFOSYS LIMITED' -> 'infosys'. Makes names comparable."""
    s = name.lower().replace("&", " ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(_SUFFIXES, " ", s)
    return re.sub(r"\s+", " ", s).strip()


@lru_cache
def _load() -> tuple[dict[str, tuple[str, str]], dict[str, str], dict[str, str]]:
    """Returns (symbol -> (name, sector), normalized name -> symbol, symbol -> file it came from)."""
    stocks: dict[str, tuple[str, str]] = {}
    names: dict[str, str] = {}
    source: dict[str, str] = {}
    for filename in FILES_IN_PRIORITY_ORDER:
        path = DATA_DIR / filename
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                sym = (row.get("Symbol") or "").strip().upper()
                if not sym:
                    continue
                name = (row.get("Company Name") or sym).strip()
                if sym not in stocks:  # first file wins for name and sector
                    stocks[sym] = (name, normalize_sector(row.get("Industry")) or "Other")
                    source[sym] = filename
                # Names and old names (aliases) from every file are kept, e.g. "Zomato" -> ETERNAL.
                for n in [name, *(row.get("Aliases") or "").split(";")]:
                    if n.strip():
                        names.setdefault(normalize_name(n), sym)
    log.info("Loaded %d stocks (%s)", len(stocks), ", ".join(sorted(set(source.values()))))
    return stocks, names, source


def reload() -> None:
    """Re-read the files (after downloading a new official list)."""
    _load.cache_clear()


def count() -> int:
    return len(_load()[0])


def has_official_list() -> bool:
    return (DATA_DIR / "nifty500.csv").exists()


def lookup(symbol: str) -> tuple[str, str] | None:
    """Return (name, sector) for a known symbol, else None."""
    return _load()[0].get(symbol.upper())


def symbol_from_name(name: str) -> str | None:
    """Match a company name (e.g. from a Groww export) to an NSE symbol.

    Tries an exact match first. Then, for names cut short by the broker
    ("TATA CONSULTANCY SERV"), a prefix match, but only if exactly one stock fits.
    Returns None rather than guessing.
    """
    key = normalize_name(name)
    if not key:
        return None
    index = _load()[1]
    if key in index:
        return index[key]
    candidates = {sym for n, sym in index.items() if n.startswith(key)}
    return candidates.pop() if len(candidates) == 1 else None
