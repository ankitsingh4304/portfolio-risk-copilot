"""One shared list of sector names, so every part of the app uses the same words.

We use NSE's official industry names (the "Industry" column in NSE's index files),
for example "Information Technology" and "Financial Services".

Sectors can come from three places, and each uses different words:
  * NSE's list:        "Information Technology"
  * Your upload file:  "IT", "Banking", "Pharma"...
  * Yahoo Finance:     "Technology", "Consumer Defensive"...
normalize_sector() turns all of them into the NSE name, so "What if IT falls 15%?"
catches every IT stock, wherever its sector came from.
"""
import re

# NSE's industry names (from the Nifty 500 list).
NSE_INDUSTRIES = [
    "Automobile and Auto Components", "Capital Goods", "Chemicals", "Construction",
    "Construction Materials", "Consumer Durables", "Consumer Services", "Diversified",
    "Fast Moving Consumer Goods", "Financial Services", "Forest Materials", "Healthcare",
    "Information Technology", "Media Entertainment & Publication", "Metals & Mining",
    "Oil Gas & Consumable Fuels", "Power", "Realty", "Services", "Telecommunication", "Textiles",
]
# Not in NSE's list, but people hold these.
OTHER_CLASSES = ["Index ETF", "Gold ETF", "Silver ETF", "Other"]

# Short words people (and older versions of this app) use -> NSE name.
SYNONYMS = {
    "it": "Information Technology", "tech": "Information Technology", "technology": "Information Technology",
    "software": "Information Technology", "information technology": "Information Technology",
    "bank": "Financial Services", "banks": "Financial Services", "banking": "Financial Services",
    "finance": "Financial Services", "financial": "Financial Services", "financials": "Financial Services",
    "nbfc": "Financial Services", "insurance": "Financial Services", "financial services": "Financial Services",
    "pharma": "Healthcare", "pharmaceuticals": "Healthcare", "health": "Healthcare",
    "healthcare": "Healthcare", "pharma & healthcare": "Healthcare", "hospitals": "Healthcare",
    "energy": "Oil Gas & Consumable Fuels", "oil": "Oil Gas & Consumable Fuels",
    "oil and gas": "Oil Gas & Consumable Fuels", "oil & gas": "Oil Gas & Consumable Fuels",
    "fmcg": "Fast Moving Consumer Goods", "consumer staples": "Fast Moving Consumer Goods",
    "auto": "Automobile and Auto Components", "autos": "Automobile and Auto Components",
    "automobile": "Automobile and Auto Components", "cars": "Automobile and Auto Components",
    "telecom": "Telecommunication", "telecommunication": "Telecommunication",
    "metal": "Metals & Mining", "metals": "Metals & Mining", "steel": "Metals & Mining", "mining": "Metals & Mining",
    "cement": "Construction Materials", "infra": "Construction", "infrastructure": "Construction",
    "real estate": "Realty", "realty": "Realty", "power": "Power", "utilities": "Power",
    "consumer": "Consumer Durables", "consumer durables": "Consumer Durables",
    "consumer services": "Consumer Services", "retail": "Consumer Services",
    "capital goods": "Capital Goods", "defence": "Capital Goods", "defense": "Capital Goods",
    "chemicals": "Chemicals", "media": "Media Entertainment & Publication", "textiles": "Textiles",
    "etf": "Index ETF", "index etf": "Index ETF", "gold": "Gold ETF",
}

# Yahoo's industry words (more detailed than its sector) -> NSE name. Checked first.
_YAHOO_INDUSTRY = [
    (r"bank|insurance|capital markets|credit|asset management|financial", "Financial Services"),
    (r"auto", "Automobile and Auto Components"),
    (r"drug|pharma|biotech|medical|health|diagnostic", "Healthcare"),
    (r"software|information technology|it services|semiconductor|computer", "Information Technology"),
    (r"oil|gas|coal|refin", "Oil Gas & Consumable Fuels"),
    (r"utilities|power|renewable", "Power"),
    (r"steel|aluminum|copper|metal|mining|gold|silver", "Metals & Mining"),
    (r"cement|building materials", "Construction Materials"),
    (r"engineering|construction", "Construction"),
    (r"telecom", "Telecommunication"),
    (r"real estate", "Realty"),
    (r"chemical", "Chemicals"),
    (r"textile|apparel", "Textiles"),
    (r"restaurant|retail|internet|travel|lodging|leisure", "Consumer Services"),
    (r"household|personal products|beverage|tobacco|packaged foods|confectioner", "Fast Moving Consumer Goods"),
    (r"aerospace|defense|electrical equipment|machinery|industrial", "Capital Goods"),
]
_YAHOO_SECTOR = {
    "technology": "Information Technology", "financial services": "Financial Services",
    "healthcare": "Healthcare", "consumer defensive": "Fast Moving Consumer Goods",
    "consumer cyclical": "Consumer Services", "energy": "Oil Gas & Consumable Fuels",
    "industrials": "Capital Goods", "basic materials": "Metals & Mining",
    "communication services": "Telecommunication", "utilities": "Power", "real estate": "Realty",
}

_CANONICAL = {s.lower(): s for s in NSE_INDUSTRIES + OTHER_CLASSES}


def _key(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def normalize_sector(name: str | None) -> str | None:
    """'IT' -> 'Information Technology'. Unknown words are kept as typed (tidied up)."""
    if not name or not name.strip():
        return None
    k = _key(name)
    if k in _CANONICAL:
        return _CANONICAL[k]
    if k in SYNONYMS:
        return SYNONYMS[k]
    return name.strip()[:80]


def from_yahoo(sector: str | None, industry: str | None) -> str | None:
    """Turn Yahoo's sector/industry into an NSE industry name."""
    ind = (industry or "").lower()
    for pattern, nse_name in _YAHOO_INDUSTRY:
        if ind and re.search(pattern, ind):
            return nse_name
    return _YAHOO_SECTOR.get((sector or "").lower())


def find_in_text(text: str) -> str | None:
    """Find a sector word inside a sentence, for the chat. 'what if banks fall' -> 'Financial Services'."""
    q = text.lower()
    names = {**_CANONICAL, **SYNONYMS}
    # Longest phrases first, so "consumer services" wins over "consumer".
    for word in sorted(names, key=len, reverse=True):
        if word == "it":
            # "it" is also a normal English word ("is it risky?"), so only count capital "IT".
            if re.search(r"\bIT\b", text):
                return names[word]
            continue
        if re.search(rf"\b{re.escape(word)}\b", q):
            return names[word]
    return None
