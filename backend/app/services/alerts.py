"""Daily checks that create alerts for each user.

Checks:
  * Big daily move      - a stock moved more than X% today
  * Drawdown            - a stock is down more than Y% from its 1-year high
  * Concentration       - one stock (or one sector) is too big a part of the portfolio
  * Volatility spike    - the portfolio is swinging much more than usual (EWMA signal, see quant.py)
  * News                - negative or important headlines about a stock you hold

Each alert has a "dedupe key", so the same alert is never created (or sent) twice.
"""
import hashlib
import html
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Alert, Holding, User
from . import telegram
from .news import fetch_news
from .portfolio_data import NoHoldingsError, analysis_window, build_snapshot, outlook
from . import risk_engine as re_

log = logging.getLogger(__name__)
settings = get_settings()

MAX_NEWS_STOCKS = 15  # keep the daily job quick
SECTOR_LIMIT_PCT = 40.0


def _key(*parts) -> str:
    return ":".join(str(p) for p in parts)


def generate_alerts(db: Session, user: User, with_news: bool = True) -> list[Alert]:
    """Run all checks for one user. Returns only the NEW alerts."""
    try:
        snap = build_snapshot(db, user)
    except NoHoldingsError:
        return []

    candidates: list[Alert] = []
    t = snap.table
    today = snap.as_of or date.today().isoformat()
    week = date.fromisoformat(today).isocalendar()
    month = today[:7]

    # 1) Big daily moves
    for sym, r in t.iterrows():
        chg = r["day_change_pct"]
        if chg is not None and abs(chg) >= settings.daily_move_threshold_pct:
            direction = "up" if chg > 0 else "down"
            severity = "critical" if abs(chg) >= 2 * settings.daily_move_threshold_pct else "warning"
            candidates.append(Alert(
                kind="price_move", severity=severity, symbol=sym,
                title=f"{sym} is {direction} {abs(chg):.1f}% today",
                body=f"Your {sym} position is now worth ₹{r['value']:,.0f} ({r['weight'] * 100:.1f}% of your portfolio).",
                dedupe_key=_key("move", sym, today),
            ))

    # 2) Drawdown from the 1-year high
    year = snap.prices.tail(252)
    for sym in t.index:
        if sym not in year or year[sym].dropna().empty:
            continue
        s = year[sym].dropna()
        dd = (s.iloc[-1] / s.max() - 1) * 100
        if dd <= -settings.drawdown_threshold_pct:
            candidates.append(Alert(
                kind="drawdown", severity="warning", symbol=sym,
                title=f"{sym} is {abs(dd):.0f}% below its 1-year high",
                body=f"High: ₹{s.max():,.2f}. Now: ₹{s.iloc[-1]:,.2f}.",
                dedupe_key=_key("drawdown", sym, week.year, week.week),
            ))

    # 3) Concentration
    top_sym = t["weight"].idxmax()
    top_w = float(t["weight"].max()) * 100
    if top_w >= settings.concentration_threshold_pct and len(t) > 1:
        candidates.append(Alert(
            kind="concentration", severity="info", symbol=top_sym,
            title=f"{top_sym} is {top_w:.0f}% of your portfolio",
            body=f"A single stock above {settings.concentration_threshold_pct:.0f}% means one bad day for it "
                 "hits your whole portfolio hard.",
            dedupe_key=_key("conc", top_sym, month),
        ))
    sector_w = t.groupby("sector")["weight"].sum() * 100
    for sector, w in sector_w.items():
        if w >= SECTOR_LIMIT_PCT and len(sector_w) > 1:
            candidates.append(Alert(
                kind="concentration", severity="info", symbol=None,
                title=f"{sector} is {w:.0f}% of your portfolio",
                body="A large share in one sector means sector-wide news moves most of your money together.",
                dedupe_key=_key("sector", sector, month),
            ))

    # 4) Volatility spike (portfolio level)
    rets, w, _, covered = analysis_window(snap)
    if covered and len(rets) >= 60:
        port = re_.portfolio_returns(rets, w)
        sig = outlook(snap, port, float(t.loc[covered, "weight"].sum()))["volatility"]
        if sig and sig["level"] == "high":
            candidates.append(Alert(
                kind="volatility", severity="warning", symbol=None,
                title=f"Your portfolio is swinging {sig['ratio']:.1f}x more than usual",
                body=f"Recent volatility is {sig['now'] * 100:.0f}% a year, against a usual {sig['typical'] * 100:.0f}%. "
                     "Big moves are more likely than normal right now.",
                dedupe_key=_key("vol", week.year, week.week),
            ))

    # 5) News (negative tone, or important event types)
    if with_news:
        for sym, r in t.head(MAX_NEWS_STOCKS).iterrows():
            for item in fetch_news(r["name"], sym, limit=6):
                important = item.tone == "negative" or item.event_type in {"regulatory", "management"}
                if not important:
                    continue
                url_hash = hashlib.sha1(item.url.encode()).hexdigest()[:16]
                candidates.append(Alert(
                    kind="news", severity="warning" if item.tone == "negative" else "info", symbol=sym,
                    title=item.title[:290], body=f"{item.source} · {item.event_type}", url=item.url,
                    dedupe_key=_key("news", url_hash),
                ))

    # Save only alerts we haven't created before.
    existing = set(db.scalars(select(Alert.dedupe_key).where(Alert.user_id == user.id)).all())
    new_alerts = []
    for a in candidates:
        if a.dedupe_key in existing:
            continue
        existing.add(a.dedupe_key)
        a.user_id = user.id
        db.add(a)
        new_alerts.append(a)
    try:
        db.commit()
    except IntegrityError:
        # Another run (e.g. "Check now" during the daily job) saved the same alerts first.
        db.rollback()
        log.info("Alerts for user %s were saved by a parallel run; skipping.", user.id)
        return []

    if user.telegram_chat_id and telegram.telegram_enabled():
        for a in new_alerts:
            text = f"<b>{html.escape(a.title)}</b>\n{html.escape(a.body)}"
            if a.url:
                text += f'\n<a href="{html.escape(a.url)}">Read more</a>'
            a.sent_telegram = telegram.send_message(user.telegram_chat_id, text)
        db.commit()
    return new_alerts


def run_daily_job(db: Session) -> dict:
    """Check every user who has holdings. Called by the scheduler."""
    user_ids = db.scalars(select(Holding.user_id).distinct()).all()
    created = 0
    for uid in user_ids:
        user = db.get(User, uid)
        try:
            created += len(generate_alerts(db, user))
        except Exception:  # noqa: BLE001  one user's problem shouldn't stop the others
            log.exception("Alert job failed for user %s", uid)
            db.rollback()
    log.info("Daily alert job: %d users, %d new alerts", len(user_ids), created)
    return {"users_checked": len(user_ids), "alerts_created": created}
