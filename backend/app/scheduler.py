"""Runs the alert job every weekday evening, after the Indian market closes."""
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import get_settings
from .database import SessionLocal
from .services.alerts import run_daily_job

log = logging.getLogger(__name__)
settings = get_settings()
_scheduler: BackgroundScheduler | None = None


def _job():
    db = SessionLocal()
    try:
        run_daily_job(db)
    finally:
        db.close()


def start_scheduler():
    global _scheduler
    if _scheduler or not settings.enable_scheduler:
        return
    _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    _scheduler.add_job(
        _job,
        CronTrigger(day_of_week="mon-fri", hour=settings.alert_hour_ist, minute=settings.alert_minute_ist),
        id="daily_alerts",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    log.info("Scheduler started: alerts at %02d:%02d IST, Mon-Fri", settings.alert_hour_ist, settings.alert_minute_ist)


def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
