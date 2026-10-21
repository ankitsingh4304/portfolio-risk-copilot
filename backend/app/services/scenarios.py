"""'What if' scenarios: how much would the portfolio lose if X happened?

Four kinds:
  1. Sector shock   - "IT falls 15%". Direct loss + estimated knock-on effect on other stocks.
  2. Market shock   - "NIFTY falls 10%". Each stock moves by (its beta x 10%).
  3. Custom shock   - "INFY -20%, HDFCBANK -5%".
  4. History replay - "What if the COVID crash happened to my portfolio today?"
"""
from dataclasses import dataclass

import pandas as pd

from . import risk_engine as re_
from .portfolio_data import Snapshot, analysis_window
from .sectors import normalize_sector


@dataclass(frozen=True)
class HistoricalEvent:
    key: str
    name: str
    start: str
    end: str
    description: str


HISTORICAL_EVENTS = {
    e.key: e
    for e in [
        HistoricalEvent("covid_2020", "COVID crash (2020)", "2020-02-19", "2020-03-23",
                        "Markets fell sharply as the pandemic spread and lockdowns began."),
        HistoricalEvent("rate_hikes_2022", "Rate-hike selloff (2022)", "2022-04-04", "2022-06-17",
                        "Global inflation and fast interest-rate hikes hit stocks."),
        HistoricalEvent("election_day_2024", "Election results day (4 Jun 2024)", "2024-06-03", "2024-06-04",
                        "A one-day fall when Lok Sabha results surprised the market."),
    ]
}

class ScenarioError(ValueError):
    pass


def resolve_sector(name: str, available: list[str]) -> str | None:
    """Match what the user typed ('IT', 'banks', 'Information Technology') to a sector they hold."""
    by_lower = {s.lower(): s for s in available}
    for candidate in (name, normalize_sector(name)):
        if candidate and candidate.strip().lower() in by_lower:
            return by_lower[candidate.strip().lower()]
    return None


def _result(name, description, snap: Snapshot, moves: dict[str, tuple[float, str]], notes: list[str]) -> dict:
    """moves: symbol -> (price move as a fraction, how we estimated it)."""
    rows, total = [], 0.0
    for sym, r in snap.table.iterrows():
        move, method = moves.get(sym, (0.0, "unaffected"))
        impact = r["value"] * move
        total += impact
        rows.append({
            "symbol": sym, "sector": r["sector"], "value": r["value"],
            "move_pct": move * 100, "impact": impact, "method": method,
        })
    rows.sort(key=lambda x: x["impact"])
    return {
        "name": name,
        "description": description,
        "current_value": snap.total_value,
        "total_impact": total,
        "total_impact_pct": (total / snap.total_value * 100) if snap.total_value else 0.0,
        "new_value": snap.total_value + total,
        "rows": rows,
        "notes": notes,
    }


def _check_pct(pct: float) -> float:
    if not -100 < pct <= 100:
        raise ScenarioError("The drop must be between 0 and 100 percent.")
    return pct


def sector_shock(snap: Snapshot, sector: str, drop_pct: float, knock_on: bool = True) -> dict:
    drop_pct = _check_pct(drop_pct)
    sectors = sorted(snap.table["sector"].unique())
    resolved = resolve_sector(sector, sectors)
    if not resolved:
        raise ScenarioError(f"You don't hold any '{sector}' stocks. Your sectors: {', '.join(sectors)}.")

    shock = -drop_pct / 100
    in_sector = list(snap.table.index[snap.table["sector"] == resolved])
    moves = {s: (shock, "direct shock") for s in in_sector}
    notes = [f"Every {resolved} stock you hold falls {drop_pct:g}%."]

    if knock_on:
        # Knock-on: other stocks that usually move with this sector tend to fall too.
        # We measure each stock's beta to a basket of your sector stocks over the past year.
        rets, w, _, covered = analysis_window(snap)
        basket_syms = [s for s in in_sector if s in covered]
        if basket_syms and len(rets) >= 30:
            bw = snap.table.loc[basket_syms, "value"]
            basket = re_.portfolio_returns(rets[basket_syms], bw / bw.sum())
            for s in covered:
                if s in in_sector:
                    continue
                b = re_.beta(rets[s], basket)
                if b is not None:
                    moves[s] = (b * shock, f"knock-on (beta {b:.2f} to {resolved})")
            notes.append(
                "Other stocks move by their past sensitivity to your sector stocks. "
                "This is an estimate from the last year, not a forecast."
            )
    return _result(f"{resolved} falls {drop_pct:g}%", f"Sector shock on {resolved}", snap, moves, notes)


def market_shock(snap: Snapshot, drop_pct: float) -> dict:
    drop_pct = _check_pct(drop_pct)
    shock = -drop_pct / 100
    rets, _, mkt, covered = analysis_window(snap)
    moves, notes = {}, []
    for s in snap.table.index:
        b = re_.beta(rets[s], mkt) if s in covered and not mkt.empty else None
        if b is None:
            moves[s] = (shock, "assumed beta 1.0 (not enough data)")
        else:
            moves[s] = (b * shock, f"beta {b:.2f}")
    notes.append("Each stock moves by its beta x the market move. Beta comes from the last year of prices.")
    return _result(f"Market falls {drop_pct:g}%", "Broad market shock (NIFTY 50)", snap, moves, notes)


def custom_shock(snap: Snapshot, shocks: dict[str, float]) -> dict:
    """shocks: symbol -> price move in percent. Negative = fall. {"INFY": -20}"""
    moves = {}
    unknown = []
    for sym, pct in shocks.items():
        s = sym.strip().upper()
        if s not in snap.table.index:
            unknown.append(sym)
            continue
        if not -100 <= pct <= 500:
            raise ScenarioError(f"Move for {s} must be between -100% and +500%.")
        moves[s] = (pct / 100, "custom")
    notes = [f"Ignored (not in your portfolio): {', '.join(unknown)}"] if unknown else []
    return _result("Custom scenario", "Your own price moves", snap, moves, notes)


def historical_replay(snap: Snapshot, event_key: str) -> dict:
    event = HISTORICAL_EVENTS.get(event_key)
    if not event:
        raise ScenarioError(f"Unknown event. Choose from: {', '.join(HISTORICAL_EVENTS)}")

    start, end = pd.Timestamp(event.start), pd.Timestamp(event.end)

    def window_return(series: pd.Series) -> float | None:
        s = series.dropna()
        before = s[s.index <= start]  # last close on/before the start = the "peak" day
        after = s[(s.index > start) & (s.index <= end)]
        if before.empty or after.empty:
            return None
        return float(after.iloc[-1] / before.iloc[-1] - 1)

    mkt_move = window_return(snap.market) if not snap.market.empty else None
    rets, _, mkt, covered = analysis_window(snap)
    moves, notes = {}, []
    for s in snap.table.index:
        actual = window_return(snap.prices[s]) if s in snap.prices else None
        if actual is not None:
            moves[s] = (actual, "actual move in that period")
        elif mkt_move is not None:
            b = re_.beta(rets[s], mkt) if s in covered and not mkt.empty else None
            moves[s] = ((b or 1.0) * mkt_move, f"estimated (wasn't trading then; beta {b or 1.0:.2f} x market)")
        else:
            moves[s] = (0.0, "no data")
    if mkt_move is not None:
        notes.append(f"NIFTY 50 moved {mkt_move * 100:.1f}% in this period.")
    notes.append(f"Period: {event.start} to {event.end}. Applied to what you hold today.")
    return _result(event.name, event.description, snap, moves, notes)
