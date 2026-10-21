"""Measure how good the AI agent is, on questions with known right answers.

For every question we check:
  1. Tool choice   - did the agent call the right tool(s)?
  2. Correctness   - does the answer contain the right number? We get the true number by
                     calling the tool ourselves.
  3. Groundedness  - is EVERY rupee amount and percentage in the answer copied from a tool
                     result? A number that isn't means the model calculated or invented it.
  4. No advice     - for "should I sell X?", the answer must not tell the user to buy or sell.
  5. Cost & speed  - tokens used and seconds taken per question.

Two question sets (eval/questions.json):
  * dev     - questions used while building the app. The basic (offline) mode was written
              around these, so it scores well on them.
  * holdout - new wordings and multi-step questions nobody tuned for ("dropped by a fifth",
              "compare X with Y"). THIS is the honest score to report.

Run from the backend folder:
    python -m eval.agent_eval                       # uses LLM_PROVIDER from your .env
    LLM_PROVIDER=offline python -m eval.agent_eval  # rule-based baseline, for comparison
    (Windows PowerShell:  $env:LLM_PROVIDER="offline"; python -m eval.agent_eval)

Optional cost estimate: set EVAL_PRICE_IN and EVAL_PRICE_OUT to your model's price in US$
per 1 million input / output tokens.

Prices come from PRICE_SOURCE (demo by default here), so results are repeatable.
Results are saved to eval/results.json.
"""
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("PRICE_SOURCE", "demo")
os.environ.setdefault("NEWS_SOURCE", "off")
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/eval.db"

from app.agent.graph import run_agent  # noqa: E402
from app.agent.tools import ToolContext, build_tools  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.models import Holding, User  # noqa: E402
from app.services import stocks_meta  # noqa: E402
from app.services.csv_parser import parse_holdings_file  # noqa: E402

HERE = Path(__file__).parent
SAMPLE = HERE.parents[1] / "sample_data" / "zerodha_kite_holdings.csv"
ADVICE = re.compile(r"\b(you should|i recommend|i'd recommend|i would recommend|i suggest you|i advise)\b[^.]*\b(sell|buy|exit|book profit)", re.I)


# ------------------------------------------------------------------ number helpers
def _num(s: str) -> float:
    return float(s.replace(",", ""))


def amounts_in(text: str) -> list[float]:
    """Rupee amounts in an answer: '₹1,23,456', 'Rs 1.2 lakh', '₹3 crore'."""
    out = []
    for m in re.finditer(r"(?:₹|rs\.?|inr)\s?(-?[\d,]*\.?\d+)\s*(lakh|lakhs|crore|crores|cr)?", text, re.I):
        v = _num(m.group(1))
        unit = (m.group(2) or "").lower()
        v *= 1e5 if unit.startswith("lakh") else 1e7 if unit.startswith("cr") else 1
        out.append(abs(v))
    return out


def percents_in(text: str) -> list[float]:
    return [abs(float(m.group(1))) for m in re.finditer(r"(-?\d+(?:\.\d+)?)\s?%", text)]


def all_numbers_in(text: str) -> list[float]:
    return [abs(_num(m.group())) for m in re.finditer(r"-?\d[\d,]*(?:\.\d+)?", text)]


def close(answer_value: float, truth: float, kind: str) -> bool:
    a, t = abs(answer_value), abs(truth)
    if kind == "inr":
        return abs(a - t) <= max(0.02 * t, 50)
    if kind == "count":
        return a == t
    if kind == "ratio":
        return abs(a - t) <= 0.02
    # Percent: allow rounding to a whole number ("about 7%" for 7.2%).
    return abs(a - t) <= (0.6 if float(a).is_integer() else 0.15)


def answer_has(answer: str, truth: float, kind: str) -> bool:
    candidates = amounts_in(answer) if kind == "inr" else all_numbers_in(answer)
    if kind == "inr":  # also accept plain numbers next to "rupees"
        candidates += all_numbers_in(answer)
    return any(close(c, truth, kind) for c in candidates)


def ungrounded_numbers(answer: str, tool_results: list[str], question: str) -> list[str]:
    """Rupee amounts and percentages in the answer that don't come from any tool result."""
    source = all_numbers_in(" ".join(tool_results))
    allowed_pcts = set(percents_in(question)) | {5.0, 95.0, 1.0, 100.0}  # "worst 5% of days", "95% VaR"
    bad = []
    for a in amounts_in(answer):
        if not any(close(a, s, "inr") for s in source):
            bad.append(f"₹{a:,.0f}")
    for p in percents_in(answer):
        if p in allowed_pcts:
            continue
        if not any(close(p, s, "pct") for s in source):
            bad.append(f"{p:g}%")
    return bad


def get_field(obj, path: str):
    for part in path.split("."):
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    return obj


# ------------------------------------------------------------------ setup
def setup_user(db) -> User:
    user = User(email="eval@example.com", password_hash="x")
    db.add(user)
    db.commit()
    for p in parse_holdings_file(SAMPLE.read_bytes(), SAMPLE.name).holdings:
        name, sector = stocks_meta.lookup(p.symbol)
        db.add(Holding(user_id=user.id, symbol=p.symbol, name=name, sector=sector,
                       quantity=p.quantity, avg_price=p.avg_price))
    db.commit()
    return user


def summarise(rows: list[dict]) -> dict:
    if not rows:
        return {}
    checks = [c for r in rows for c in r["checks"]]
    numeric = [r for r in rows if r["numbers_in_answer"]]
    advice = [r for r in rows if r.get("must_not_advise")]
    tokens_in = sum(r["tokens_in"] for r in rows)
    tokens_out = sum(r["tokens_out"] for r in rows)
    price_in = float(os.environ.get("EVAL_PRICE_IN", "0"))
    price_out = float(os.environ.get("EVAL_PRICE_OUT", "0"))
    return {
        "questions": len(rows),
        "tool_accuracy": sum(r["tool_ok"] for r in rows) / len(rows),
        "number_accuracy": (sum(c["ok"] for c in checks) / len(checks)) if checks else None,
        "groundedness": (sum(not r["ungrounded"] for r in numeric) / len(numeric)) if numeric else None,
        "no_advice_rate": (sum(r["advice_ok"] for r in advice) / len(advice)) if advice else None,
        "avg_latency_s": round(sum(r["latency_s"] for r in rows) / len(rows), 2),
        "avg_tokens": round((tokens_in + tokens_out) / len(rows)),
        "est_cost_usd_per_question": round((tokens_in * price_in + tokens_out * price_out) / 1e6 / len(rows), 6)
        if (price_in or price_out) else None,
    }


def fmt(x):
    return "-" if x is None else f"{x:.0%}" if isinstance(x, float) and x <= 1 else str(x)


def main():
    settings = get_settings()
    init_db()
    db = SessionLocal()
    user = setup_user(db)
    cases = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))
    only = os.environ.get("EVAL_SET")  # "dev" or "holdout" to run one set
    cases = [c for c in cases if not only or c["set"] == only]
    tools = {t.name: t for t in build_tools(ToolContext(db, user))}

    rows = []
    for i, case in enumerate(cases, 1):
        t0 = time.time()
        out = run_agent(db, user, case["question"], [])
        latency = time.time() - t0
        called = [c["tool"] for c in out["tool_calls"]]
        expected = case["expect_tools"]
        tool_ok = any(t in called for t in expected) if case.get("any_of") else all(t in called for t in expected)

        checks = []
        for chk in case["checks"]:
            truth = get_field(tools[chk["tool"]].invoke(chk.get("args", {})), chk["field"])
            checks.append({"field": chk["field"], "truth": truth, "ok": answer_has(out["answer"], truth, chk["kind"])})

        bad = ungrounded_numbers(out["answer"], out.get("tool_results", []), case["question"])
        advice_ok = not ADVICE.search(out["answer"]) if case.get("must_not_advise") else None
        usage = out.get("usage") or {}
        row = {
            **case, "answer": out["answer"], "called": called, "tool_ok": tool_ok, "checks": checks,
            "numbers_in_answer": bool(amounts_in(out["answer"]) or percents_in(out["answer"])),
            "ungrounded": bad, "advice_ok": advice_ok, "latency_s": round(latency, 2),
            "tokens_in": usage.get("input_tokens", 0), "tokens_out": usage.get("output_tokens", 0), "mode": out["mode"],
        }
        ok = tool_ok and all(c["ok"] for c in checks) and not bad and advice_ok is not False
        note = (" ungrounded: " + ", ".join(bad)) if bad else ""
        print(f"[{'PASS' if ok else 'FAIL'}] {case['id']} {case['question'][:58]:58s} tools={called}{note} ({latency:.1f}s)")
        rows.append(row)
        if settings.llm_provider == "gemini":
            time.sleep(float(os.environ.get("EVAL_SLEEP", "6")))  # stay under free-tier rate limits

    summary = {"mode": rows[0]["mode"] if rows else None}
    for name in ("dev", "holdout"):
        summary[name] = summarise([r for r in rows if r["set"] == name])
    summary["all"] = summarise(rows)

    print(f"\nMode: {summary['mode']}")
    print(f"{'':10s}{'questions':>10s}{'tools':>8s}{'numbers':>9s}{'grounded':>10s}{'no advice':>11s}{'latency':>9s}{'tokens':>8s}")
    for name in ("dev", "holdout", "all"):
        s = summary[name]
        if s:
            print(f"{name:10s}{s['questions']:>10d}{fmt(s['tool_accuracy']):>8s}{fmt(s['number_accuracy']):>9s}"
                  f"{fmt(s['groundedness']):>10s}{fmt(s['no_advice_rate']):>11s}{s['avg_latency_s']:>8.1f}s{s['avg_tokens']:>8d}")
    (HERE / "results.json").write_text(json.dumps({"summary": summary, "results": rows}, indent=2,
                                                  ensure_ascii=False, default=str), encoding="utf-8")
    db.close()
    strict = "--strict" in sys.argv  # CI could use this to fail the build on a bad score
    return 1 if strict and summary["all"]["tool_accuracy"] < 1 else 0


if __name__ == "__main__":
    sys.exit(main())
