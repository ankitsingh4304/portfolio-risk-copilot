"""Download NSE's official Nifty 500 list (company, industry, symbol) into app/data/nifty500.csv.

Run from the backend folder:
    python -m scripts.update_stock_list

NSE updates the list twice a year. Run this again then. If NSE blocks the download
(it sometimes blocks scripts), open the URL below in your browser, save the file as
backend/app/data/nifty500.csv, and restart the app.
"""
import csv
import io
import sys
from pathlib import Path

import httpx

URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
OUT = Path(__file__).resolve().parents[1] / "app" / "data" / "nifty500.csv"
REQUIRED = {"Company Name", "Industry", "Symbol"}


def main() -> int:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "text/csv,*/*"}
    try:
        r = httpx.get(URL, headers=headers, timeout=30, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"Download failed: {exc}\nOpen {URL} in a browser and save it as {OUT}")
        return 1

    rows = list(csv.DictReader(io.StringIO(r.text.lstrip("﻿"))))
    if not rows or not REQUIRED <= set(rows[0]):
        print(f"Unexpected file format. Columns found: {list(rows[0]) if rows else 'none'}")
        return 1
    if len(rows) < 400:
        print(f"Only {len(rows)} rows. Expected about 500. Not saving.")
        return 1

    OUT.write_text(r.text.lstrip("﻿"), encoding="utf-8")
    industries = sorted({row["Industry"] for row in rows})
    print(f"Saved {len(rows)} stocks to {OUT}")
    print(f"{len(industries)} industries: {', '.join(industries)}")
    print("Restart the backend to use it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
