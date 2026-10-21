"""Read a holdings file exported from a broker.

Supported out of the box (CSV, Excel, or PDF; see pdf_extract.py for PDFs):
  * Zerodha Kite holdings export   (Instrument, Qty., Avg. cost, ...)
  * Zerodha Console holdings       (Symbol, Quantity Available, Average Price, ...)
  * Groww holdings statement       (Stock Name, Quantity, Average buy price, ...)
  * A simple template              (symbol, quantity, avg_price, [sector])

Works with .csv and .xlsx. Header rows can be anywhere in the first 30 rows
(Console and Groww files have a few title rows above the table).
"""
import csv
import io
import re
from dataclasses import dataclass, field

import pandas as pd

from . import stocks_meta

COLUMN_ALIASES = {
    "symbol": {"symbol", "instrument", "tradingsymbol", "trading symbol", "ticker", "scrip", "stock symbol"},
    "name": {"stock name", "company name", "company", "name", "security name"},
    "quantity": {"qty", "quantity", "quantity available", "shares", "units", "qty available"},
    "avg_price": {
        "avg cost", "average cost", "average price", "avg price", "average buy price",
        "avg buy price", "buy price", "buy avg", "avg_price",
    },
    "sector": {"sector", "industry"},
}


@dataclass
class ParsedHolding:
    symbol: str
    quantity: float
    avg_price: float
    name: str = ""
    sector: str | None = None


@dataclass
class ParseResult:
    holdings: list[ParsedHolding] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    detected_format: str = "unknown"


class ParseError(ValueError):
    pass


def _norm_header(h) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9_ ]", " ", str(h).lower())).strip()


def clean_symbol(raw: str) -> str:
    """'NSE:INFY-EQ' -> 'INFY'."""
    s = str(raw).strip().upper()
    s = re.sub(r"^(NSE|BSE)\s*:\s*", "", s)
    s = re.sub(r"-(EQ|BE|BZ|SM|ST)$", "", s)
    s = re.sub(r"\.(NS|BO)$", "", s)
    return s.strip()


def _to_number(v) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = re.sub(r"[₹,\s]", "", str(v))
    try:
        return float(s)
    except ValueError:
        return None


def _read_raw(content: bytes, filename: str) -> pd.DataFrame:
    """Read every cell as text with no header, so we can find the header row ourselves."""
    lower = filename.lower()
    try:
        if lower.endswith((".xlsx", ".xls")):
            return pd.read_excel(io.BytesIO(content), header=None, dtype=str)
        # Read with the csv module: title rows above the table have fewer columns,
        # which pandas would treat as "bad lines" and drop.
        text = content.decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
        width = max((len(r) for r in rows), default=0)
        return pd.DataFrame([r + [None] * (width - len(r)) for r in rows])
    except Exception as exc:  # noqa: BLE001
        raise ParseError(f"Could not read the file: {exc}") from exc


def _map_columns(header_cells: list) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, cell in enumerate(header_cells):
        h = _norm_header(cell)
        for field_name, aliases in COLUMN_ALIASES.items():
            if field_name not in mapping and h in aliases:
                mapping[field_name] = idx
    return mapping


def parse_holdings_file(content: bytes, filename: str, llm=None) -> ParseResult:
    """Read holdings from a CSV, Excel or PDF file. `llm` is only used for PDFs without a table."""
    if filename.lower().endswith(".pdf") or content[:5] == b"%PDF-":
        from .pdf_extract import parse_pdf  # imported here to keep CSV uploads light

        return parse_pdf(content, llm=llm)
    raw = _read_raw(content, filename)
    if raw.empty:
        raise ParseError("The file is empty.")
    return parse_grid(raw)


def is_header_row(cells: list) -> bool:
    m = _map_columns(cells)
    return "quantity" in m and ("symbol" in m or "name" in m) and "avg_price" in m


def parse_grid(raw: pd.DataFrame) -> ParseResult:
    """Find the holdings table inside a grid of cells (from a CSV, an Excel sheet, or a PDF table)."""

    # 1) Find the header row: first row that has a quantity column and (symbol or name).
    header_row, mapping = None, {}
    for i in range(min(30, len(raw))):
        m = _map_columns(list(raw.iloc[i].values))
        if "quantity" in m and ("symbol" in m or "name" in m) and "avg_price" in m:
            header_row, mapping = i, m
            break
    if header_row is None:
        raise ParseError(
            "Couldn't find the holdings table. The file needs columns for symbol (or stock name), "
            "quantity and average price. Zerodha and Groww exports work as-is."
        )

    result = ParseResult()
    headers = {_norm_header(c) for c in raw.iloc[header_row].values}
    if "instrument" in headers:
        result.detected_format = "Zerodha Kite"
    elif "quantity available" in headers:
        result.detected_format = "Zerodha Console"
    elif "average buy price" in headers:
        result.detected_format = "Groww"
    else:
        result.detected_format = "Simple template"

    merged: dict[str, ParsedHolding] = {}
    for i in range(header_row + 1, len(raw)):
        row = raw.iloc[i].values
        line = i + 1  # 1-based row number the user sees in Excel

        def cell(key):
            idx = mapping.get(key)
            return row[idx] if idx is not None and idx < len(row) else None

        if i > header_row and is_header_row(list(row)):
            continue  # header repeated at the top of the next PDF page

        qty = _to_number(cell("quantity"))
        avg = _to_number(cell("avg_price"))
        raw_symbol = cell("symbol")
        raw_name = cell("name")
        if qty is None and avg is None and not raw_symbol and not raw_name:
            continue  # blank line or footer
        if raw_symbol is None and raw_name is None:
            continue
        # Skip "Total" rows some exports add at the bottom.
        label = str(raw_symbol or raw_name or "").strip().lower()
        if label in {"total", "grand total", "nan", ""}:
            continue

        symbol = clean_symbol(raw_symbol) if raw_symbol and str(raw_symbol).lower() != "nan" else None
        name = str(raw_name).strip() if raw_name and str(raw_name).lower() != "nan" else ""
        if not symbol and name:
            symbol = stocks_meta.symbol_from_name(name)
            if not symbol:
                result.warnings.append(
                    f"Row {line}: couldn't match '{name}' to an NSE symbol. Add it manually with its symbol."
                )
                continue
        if len(symbol) > 40:
            result.warnings.append(f"Row {line}: '{symbol[:20]}…' doesn't look like a stock symbol, skipped.")
            continue
        if qty is None or qty <= 0:
            result.warnings.append(f"Row {line} ({symbol}): quantity missing or zero, skipped.")
            continue
        if avg is None or avg < 0:
            result.warnings.append(f"Row {line} ({symbol}): average price missing, using 0.")
            avg = 0.0

        sector = cell("sector")
        sector = str(sector).strip() if sector and str(sector).lower() != "nan" else None

        if symbol in merged:  # same stock twice -> combine with a weighted average price
            h = merged[symbol]
            total_qty = h.quantity + qty
            h.avg_price = (h.avg_price * h.quantity + avg * qty) / total_qty
            h.quantity = total_qty
        else:
            merged[symbol] = ParsedHolding(symbol=symbol, quantity=qty, avg_price=avg, name=name[:200],
                                           sector=sector[:80] if sector else None)

    if not merged:
        raise ParseError("No valid holdings found in the file. " + " ".join(result.warnings[:3]))
    result.holdings = list(merged.values())
    return result
