"""Build a downloadable Excel risk report (one file, several sheets).

Sheets:
  Summary       - the headline numbers in plain words
  Holdings      - every stock: value, weight, profit/loss, volatility, beta, share of risk
  Sectors       - money per sector
  Scenarios     - each sector falling 10%, the market falling 10%, and past crash replays
  Correlation   - which stocks move together (colour-coded)
  Daily history - what Rs 100 became each day, with drawdown and EWMA volatility
"""
import io

import pandas as pd
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import scenarios as sc
from .portfolio_data import Snapshot, risk_report

HEADER_FILL = PatternFill("solid", fgColor="DCE3F7")
INR = '"₹"#,##0'
PCT = "0.0%"


def _summary_rows(rep: dict) -> list[tuple[str, object, str, str]]:
    """(label, value, number format, plain-words explanation)."""
    m, c, o = rep["metrics"] or {}, rep["concentration"], rep.get("outlook") or {}
    rows = [
        ("Prices up to", rep["as_of"], "@", ""),
        ("Portfolio value", rep["total_value"], INR, "Quantity x latest price, added up"),
        ("Amount invested", rep["total_cost"], INR, "Quantity x your average buy price"),
        ("Profit / loss", rep["total_pnl"], INR, ""),
        ("Largest holding", f"{c['top_holding']['symbol']} ({c['top_holding']['weight']:.1%})" if c["top_holding"] else "-", "@", ""),
        ("Spread like N equal stocks", c["effective_holdings"], "0.0", "1 / sum of squared weights"),
    ]
    if m:
        rows += [
            ("1-day Value at Risk (95%)", m["var_95_amount"], INR, "Loss beaten on only 1 day in 20 (past year)"),
            ("Expected shortfall (95%)", m["cvar_95_amount"], INR, "Average loss on those worst 1-in-20 days"),
            ("Yearly volatility", m["annual_volatility"], PCT, "How much the value swings in a year"),
            ("Max drawdown (1 year)", m["max_drawdown"], PCT, f"From {m['drawdown_peak']} to {m['drawdown_trough']}"),
            ("Beta vs NIFTY 50", m["beta"], "0.00", "Move for a 1% NIFTY move"),
            ("Sharpe ratio", m["sharpe"], "0.00", f"Return above {m['risk_free_rate']:.1%} per unit of risk"),
            ("Return over the past year", m["annual_return"], PCT, ""),
        ]
    if o.get("volatility"):
        v = o["volatility"]
        rows.append(("Volatility now (EWMA)", v["now"], PCT, f"Usual: {v['typical']:.1%}. Right now: {v['text']}"))
    if o.get("month"):
        mo = o["month"]
        rows += [
            ("Bad month, 1 in 20 (Monte Carlo)", mo["bad_month"], PCT, f"{mo['paths']:,} simulated months"),
            ("Chance of losing more than 10% in a month", mo["prob_loss_over_10"], PCT, ""),
        ]
    if o.get("var_backtest"):
        b = o["var_backtest"]
        rows.append(("VaR backtest", f"{b['breaches']} breaches in {b['days_tested']} days "
                     f"(expected {b['expected']:.1f}), {'passed' if b['passed'] else 'failed'}", "@",
                     f"Kupiec p-value {b['p_value']:.2f}"))
    return rows


def _scenario_rows(snap: Snapshot) -> list[dict]:
    rows = []
    runs = [(f"{s} falls 10%", lambda s=s: sc.sector_shock(snap, s, 10)) for s in sorted(snap.table["sector"].unique())]
    runs.append(("NIFTY 50 falls 10%", lambda: sc.market_shock(snap, 10)))
    runs += [(e.name, lambda k=k: sc.historical_replay(snap, k)) for k, e in sc.HISTORICAL_EVENTS.items()]
    for label, fn in runs:
        try:
            r = fn()
        except sc.ScenarioError:
            continue
        rows.append({"Scenario": label, "Change (₹)": r["total_impact"], "Change (%)": r["total_impact_pct"] / 100,
                     "Value after (₹)": r["new_value"],
                     "Biggest ₹ hit": f"{r['rows'][0]['symbol']} ({r['rows'][0]['move_pct']:+.1f}%)" if r["rows"] else ""})
    return rows


def _style(ws, formats: dict[str, str] | None = None, widths: dict[str, int] | None = None):
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="center")
    ws.freeze_panes = "A2"
    headers = {c.value: c.column_letter for c in ws[1]}
    for name, fmt in (formats or {}).items():
        col = headers.get(name)
        if col:
            for cell in ws[col][1:]:
                cell.number_format = fmt
    for col_cells in ws.columns:
        letter = col_cells[0].column_letter
        longest = max((len(str(c.value)) for c in col_cells if c.value is not None), default=8)
        ws.column_dimensions[letter].width = (widths or {}).get(letter, min(max(10, longest + 2), 60))


def build_excel(snap: Snapshot) -> bytes:
    rep = risk_report(snap)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        # Summary
        summary = _summary_rows(rep)
        pd.DataFrame([(a, b, d) for a, b, _, d in summary], columns=["Measure", "Value", "What it means"]) \
            .to_excel(xw, sheet_name="Summary", index=False)
        ws = xw.sheets["Summary"]
        for i, (_, _, fmt, _) in enumerate(summary, start=2):
            ws.cell(row=i, column=2).number_format = fmt
        _style(ws)

        # Holdings
        h = pd.DataFrame(rep["holdings"])
        cols = {"symbol": "Symbol", "name": "Company", "sector": "Sector", "quantity": "Quantity",
                "avg_price": "Avg price (₹)", "last_price": "Last price (₹)", "value": "Value (₹)",
                "weight": "Weight", "pnl": "Profit/loss (₹)", "pnl_pct": "Profit/loss (%)",
                "annual_volatility": "Yearly volatility", "beta": "Beta", "risk_share": "Share of risk"}
        h = h[list(cols)].rename(columns=cols)
        h["Profit/loss (%)"] = h["Profit/loss (%)"] / 100
        h.to_excel(xw, sheet_name="Holdings", index=False)
        _style(xw.sheets["Holdings"], {"Avg price (₹)": "#,##0.00", "Last price (₹)": "#,##0.00", "Value (₹)": INR,
                                        "Profit/loss (₹)": INR, "Weight": PCT, "Profit/loss (%)": PCT,
                                        "Yearly volatility": PCT, "Beta": "0.00", "Share of risk": PCT})

        # Sectors
        pd.DataFrame(list(rep["concentration"]["sector_weights"].items()), columns=["Sector", "Weight"]) \
            .to_excel(xw, sheet_name="Sectors", index=False)
        _style(xw.sheets["Sectors"], {"Weight": PCT})

        # Scenarios
        pd.DataFrame(_scenario_rows(snap)).to_excel(xw, sheet_name="Scenarios", index=False)
        _style(xw.sheets["Scenarios"], {"Change (₹)": INR, "Change (%)": PCT, "Value after (₹)": INR})

        # Correlation
        cm = rep.get("correlation_matrix")
        if cm:
            df = pd.DataFrame(cm["values"], index=cm["symbols"], columns=cm["symbols"])
            df.to_excel(xw, sheet_name="Correlation")
            ws = xw.sheets["Correlation"]
            n = len(cm["symbols"])
            rng = f"B2:{get_column_letter(n + 1)}{n + 1}"
            ws.conditional_formatting.add(rng, ColorScaleRule(start_type="num", start_value=-1, start_color="F6E1E5",
                                                              mid_type="num", mid_value=0, mid_color="FFFFFF",
                                                              end_type="num", end_value=1, end_color="5B79E0"))
            for row in ws.iter_rows(min_row=2, min_col=2):
                for cell in row:
                    cell.number_format = "0.00"
            ws.column_dimensions["A"].width = 14

        # Daily history
        if rep.get("history"):
            hist = pd.DataFrame(rep["history"]).rename(columns={
                "date": "Date", "portfolio": "Portfolio (₹100 start)", "market": "NIFTY 50 (₹100 start)",
                "drawdown": "Below last high (%)", "ewma_vol": "EWMA volatility (%)"})
            hist.to_excel(xw, sheet_name="Daily history", index=False)
            _style(xw.sheets["Daily history"])
    return buf.getvalue()
