"""A simple rule-based 'agent' used when no LLM key is set (or the LLM is down).

It reads the question with a few patterns, calls the same tools the real agent
uses, and fills in a template. Less flexible than the LLM, but always works and
costs nothing. Also handy as a baseline when evaluating the real agent.
"""
import json
import re

from ..services.sectors import find_in_text


def _inr(x) -> str:
    """Indian number format: 1234567 -> ₹12,34,567"""
    if x is None:
        return "n/a"
    neg = x < 0
    s = str(int(round(abs(x))))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = ",".join(re.findall(r"\d{1,2}", head[::-1]))[::-1]
        s = f"{head},{tail}"
    return f"-₹{s}" if neg else f"₹{s}"


def _call(tools, name, **args):
    tool = next(t for t in tools if t.name == name)
    result = tool.invoke(args)
    return result, {"tool": name, "args": args, "_result": result}


def _scenario_text(r: dict) -> str:
    if "error" in r:
        return r["error"]
    hits = ", ".join(f"{h['symbol']} {h['move_pct']:+.1f}%" for h in r["biggest_hits"][:3])
    return (
        f"**{r['scenario']}**: your portfolio would change by about {_inr(r['estimated_change_inr'])} "
        f"({r['estimated_change_pct']:+.1f}%), from {_inr(r['current_value_inr'])} to {_inr(r['value_after_inr'])}.\n\n"
        f"Biggest hits: {hits}.\n\nThis is an estimate from past prices, not a prediction."
    )


def answer(message: str, tools) -> dict:
    """Same output shape as the real agent: answer, tool calls, tool results (for evaluation)."""
    out = _answer(message, tools)
    out["tool_results"] = [json.dumps(c.pop("_result"), default=str) for c in out["tool_calls"]]
    out["usage"] = {"input_tokens": 0, "output_tokens": 0}
    return out


def _answer(message: str, tools) -> dict:
    q = message.lower()
    calls = []
    pct_match = re.search(r"(\d+(?:\.\d+)?)\s*(%|percent|pc\b)", q)
    pct = float(pct_match.group(1)) if pct_match else None

    # Historical replays
    event = ("covid_2020" if re.search(r"covid|2020|pandemic", q)
             else "rate_hikes_2022" if re.search(r"2022|rate hike", q)
             else "election_day_2024" if re.search(r"election|2024", q) else None)
    sector = find_in_text(message)
    holdings_overview, c = _call(tools, "get_portfolio_overview")
    calls.append(c)
    if "error" in holdings_overview:
        return {"answer": holdings_overview["error"], "tool_calls": calls, "mode": "offline"}
    symbols = [h["symbol"] for h in holdings_overview["holdings"]]
    symbol = next((s for s in symbols if re.search(rf"\b{re.escape(s.lower())}\b", q)), None)

    if event:
        r, c = _call(tools, "run_historical_scenario", event=event)
        calls.append(c)
        text = _scenario_text(r)
    elif pct and re.search(r"market|nifty|sensex|everything", q):
        r, c = _call(tools, "run_market_scenario", drop_pct=pct)
        calls.append(c)
        text = _scenario_text(r)
    elif pct and sector:
        r, c = _call(tools, "run_sector_scenario", sector=sector, drop_pct=pct)
        calls.append(c)
        text = _scenario_text(r)
    elif pct and symbol:
        sign = 1 if re.search(r"rise|rises|up|gain|jump", q) else -1
        r, c = _call(tools, "run_custom_scenario", symbols=[symbol], moves_pct=[sign * pct])
        calls.append(c)
        text = _scenario_text(r)
    elif symbol and re.search(r"news|headline|happen", q):
        r, c = _call(tools, "get_stock_news", symbol=symbol)
        calls.append(c)
        if r.get("headlines"):
            lines = "\n".join(f"- {h['title']} ({h['source']}, {h['tone']})" for h in r["headlines"][:5])
            text = f"Recent headlines for {symbol}:\n{lines}"
        else:
            text = r.get("note") or r.get("error", "No news found.")
    elif symbol:
        r, c = _call(tools, "get_stock_details", symbol=symbol)
        calls.append(c)
        text = (
            f"**{symbol}** is {r['weight_pct']}% of your portfolio ({_inr(r['value_inr'])}). "
            f"Its yearly volatility is {r['annual_volatility_pct']}% and its beta is {r['beta_vs_nifty']} "
            f"(it moves about {r['beta_vs_nifty']}% when NIFTY moves 1%). "
            f"It causes {r['share_of_portfolio_risk_pct']}% of your portfolio's risk."
        ) if "error" not in r else r["error"]
    elif re.search(r"next month|forecast|outlook|chance|probab|rising|higher than (usual|normal)|monte carlo|backtest", q):
        r, c = _call(tools, "get_risk_outlook")
        calls.append(c)
        if "error" in r:
            text = r["error"]
        else:
            parts = []
            if "volatility_now_pct" in r:
                parts.append(f"Right now your portfolio is swinging {r['volatility_vs_usual']} "
                             f"({r['volatility_now_pct']}% a year vs a usual {r['volatility_usual_pct']}%).")
            if "next_month_bad_case_pct" in r:
                parts.append(f"In a bad month (1 in 20), you could be down about {abs(r['next_month_bad_case_pct'])}% "
                             f"({_inr(abs(r['next_month_bad_case_inr']))}). Chance of losing more than 10% in a month: "
                             f"{r['chance_of_losing_over_10pct']}%.")
            if "var_backtest" in r:
                b = r["var_backtest"]
                parts.append(f"Our bad-day estimate was beaten {b['breaches']} times in {b['days_tested']} days "
                             f"(about {b['expected_breaches']} expected), so it {'passed' if b['passed'] else 'failed'} its check.")
            text = "\n\n".join(parts) + "\n\nThis comes from 10,000 simulated months built from past days, not a prediction."
    elif re.search(r"correlat|together|diversif", q):
        r, c = _call(tools, "get_correlated_pairs")
        calls.append(c)
        pairs = "\n".join(f"- {p['a']} & {p['b']}: {p['correlation']}" for p in r["pairs"])
        text = ("These pairs move together the most (1.0 = always together, 0 = unrelated):\n"
                f"{pairs}\n\nStocks that move together don't protect each other in a fall.")
    elif re.search(r"risk|volatil|drawdown|\bvar\b|sharpe|beta|safe|lose|loss", q):
        r, c = _call(tools, "get_risk_metrics")
        calls.append(c)
        if "error" in r:
            text = r["error"]
        else:
            top = r["top_risk_contributors"][0]
            text = (
                f"Your portfolio's yearly volatility is {r['annual_volatility_pct']}% "
                f"(NIFTY: {r['nifty_annual_volatility_pct']}%). Volatility means how much the value swings.\n\n"
                f"- Biggest fall in the last year: {r['max_drawdown_pct']}%.\n"
                f"- On a bad day (worst 5% of days), you could lose about {_inr(r['var_95_one_day_inr'])} or more.\n"
                f"- Beta {r['beta_vs_nifty']}: when NIFTY moves 1%, you move about {r['beta_vs_nifty']}%.\n"
                f"- {top['symbol']} is {top['weight_pct']}% of your money but {top['share_of_risk_pct']}% of your risk."
            )
    else:
        o = holdings_overview
        top = sorted(o["holdings"], key=lambda h: h["weight_pct"], reverse=True)[:3]
        top_txt = ", ".join(f"{h['symbol']} ({h['weight_pct']}%)" for h in top)
        text = (
            f"Your portfolio is worth {_inr(o['total_value_inr'])}. You invested {_inr(o['invested_inr'])}, "
            f"so you're at {_inr(o['profit_loss_inr'])} ({o['profit_loss_pct']:+.1f}%).\n\n"
            f"Largest holdings: {top_txt}.\n\n"
            "Try asking: \"How risky is my portfolio?\", \"What if IT stocks fall sharply?\", or \"Replay the COVID crash\"."
        )
    return {"answer": text, "tool_calls": calls, "mode": "offline"}
