import pytest

from app.services.csv_parser import ParseError, clean_symbol, parse_holdings_file
from app.services.stocks_meta import symbol_from_name

from .conftest import SAMPLE_DIR


def by_symbol(result):
    return {h.symbol: h for h in result.holdings}


def test_zerodha_kite_sample():
    res = parse_holdings_file((SAMPLE_DIR / "zerodha_kite_holdings.csv").read_bytes(), "h.csv")
    assert res.detected_format == "Zerodha Kite"
    h = by_symbol(res)
    assert len(h) == 10
    assert h["INFY"].quantity == 40 and h["INFY"].avg_price == 1420.50


def test_groww_with_title_rows_and_names():
    res = parse_holdings_file((SAMPLE_DIR / "groww_holdings.csv").read_bytes(), "h.csv")
    assert res.detected_format == "Groww"
    assert set(by_symbol(res)) == {"INFY", "TCS", "HDFCBANK", "RELIANCE", "ITC", "BHARTIARTL"}


def test_zerodha_console_format():
    csv = (
        "Equity Holdings Statement as on 2026-10-20\n\n"
        "Symbol,ISIN,Sector,Quantity Available,Quantity Discrepant,Average Price,Previous Closing Price\n"
        "INFY-EQ,X,IT,10,0,\"1,500.00\",1550\n"
        "SBIN,X,Banks,5,0,800,810\n"
    ).encode()
    res = parse_holdings_file(csv, "console.csv")
    assert res.detected_format == "Zerodha Console"
    h = by_symbol(res)
    assert h["INFY"].avg_price == 1500.0  # comma in number handled
    assert h["SBIN"].sector == "Banks"


def test_duplicates_merged_and_total_row_skipped():
    csv = b"symbol,quantity,avg_price\nINFY,10,100\nNSE:INFY,30,200\nTotal,40,\n"
    h = by_symbol(parse_holdings_file(csv, "x.csv"))
    assert list(h) == ["INFY"]
    assert h["INFY"].quantity == 40
    assert h["INFY"].avg_price == pytest.approx((10 * 100 + 30 * 200) / 40)


def test_zero_quantity_skipped_with_warning():
    res = parse_holdings_file(b"symbol,quantity,avg_price\nINFY,0,100\nTCS,1,3000\n", "x.csv")
    assert list(by_symbol(res)) == ["TCS"]
    assert any("INFY" in w for w in res.warnings)


def test_unmatched_name_warns():
    csv = b"Stock Name,Quantity,Average buy price\nSOME UNKNOWN CO LTD,5,10\nINFOSYS LIMITED,1,1500\n"
    res = parse_holdings_file(csv, "x.csv")
    assert list(by_symbol(res)) == ["INFY"]
    assert any("SOME UNKNOWN" in w for w in res.warnings)


def test_missing_columns_error():
    with pytest.raises(ParseError, match="Couldn't find"):
        parse_holdings_file(b"foo,bar\n1,2\n", "x.csv")


def test_clean_symbol():
    assert clean_symbol(" nse:infy-eq ") == "INFY"
    assert clean_symbol("RELIANCE.NS") == "RELIANCE"
    assert clean_symbol("M&M") == "M&M"


def test_name_matching_is_strict():
    assert symbol_from_name("HDFC BANK LTD") == "HDFCBANK"
    assert symbol_from_name("HDFC") is None  # ambiguous: HDFC Bank or HDFC Life
    assert symbol_from_name("ITC HOTELS LTD") is None  # must not map to ITC


def test_excel_file():
    import io

    import pandas as pd

    buf = io.BytesIO()
    pd.DataFrame({"Symbol": ["INFY", "TCS"], "Quantity": [3, 4], "Average Price": [1500, 3000]}).to_excel(buf, index=False)
    h = by_symbol(parse_holdings_file(buf.getvalue(), "holdings.xlsx"))
    assert h["TCS"].quantity == 4 and h["INFY"].avg_price == 1500


def _arihant_xlsx() -> bytes:
    """An Arihant back-office holdings report (made-up client and numbers), as Excel."""
    import io

    import pandas as pd

    head = ["Client Code", "Client Name", "Scrip Code", "ISIN", "Security Name", "Holding", "Colletral",
            "DP Holding", "Total Holding", "Close Rate", "VAR %", "Category", "Margin Pledge Value",
            "Holding Value", "Value After VAR", "Buy Avg", "Notional PNL", "Investment Value"]
    blank = [None] * len(head)
    rows = [
        ["ARIHANT CAPITAL MARKETS LIMITED"] + blank[1:],
        ["Client Holding ason 01/10/2026"] + blank[1:],
        blank, blank,
        head,
        ["X1", "TEST USER", "500325", "INE002A01018", "RELIANCE", 0, 0, 3, 3, 1200, 9, None, 0, 3600, 3276, 1100, 300, 3300],
        ["X1", "TEST USER", "500209", "INE009A01021", "INFY", 0, 0, 10, 10, 1500, 9, None, 0, 15000, 13650, 1400.5, 995, 14005],
        ["X1", "TEST USER", "999999", "INE000X01010", "NEWLISTCO", 0, 0, 7, 7, 50, 15, None, 0, 350, 300, 40, 70, 280],
        [None, "Client Total"] + blank[2:],
        [None, "Grand Total"] + blank[2:],
    ]
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, header=False, index=False)
    return buf.getvalue()


def test_arihant_back_office_report():
    res = parse_holdings_file(_arihant_xlsx(), "ClientBeneficiaryHolding.xlsx")
    assert res.detected_format == "Arihant"
    h = by_symbol(res)
    assert set(h) == {"RELIANCE", "INFY", "NEWLISTCO"}  # total rows skipped
    # Quantity must come from "Total Holding", not "Holding" (free shares, 0 here).
    assert h["RELIANCE"].quantity == 3 and h["RELIANCE"].avg_price == 1100
    assert h["INFY"].quantity == 10 and h["INFY"].avg_price == 1400.5
    # A symbol not in our list is kept: Yahoo is asked for its prices and sector later.
    assert h["NEWLISTCO"].quantity == 7
    assert not res.warnings


def test_isin_beats_a_misleading_name(monkeypatch):
    from app.services import csv_parser, stocks_meta

    monkeypatch.setattr(stocks_meta, "symbol_from_isin", lambda isin: {"INE009A01021": "INFY"}.get(isin))
    csv = "ISIN,Security Name,Total Holding,Buy Avg\nINE009A01021,INFOSYS LTD (OLD NAME),4,1500\n".encode()
    res = csv_parser.parse_holdings_file(csv, "h.csv")
    assert by_symbol(res)["INFY"].quantity == 4


def test_name_with_spaces_is_not_guessed_as_symbol():
    csv = "Security Name,Total Holding,Buy Avg\nSOME UNKNOWN COMPANY LTD,4,100\nINFY,2,1500\n".encode()
    res = parse_holdings_file(csv, "h.csv")
    assert set(by_symbol(res)) == {"INFY"}
    assert "SOME UNKNOWN COMPANY LTD" in res.warnings[0]
