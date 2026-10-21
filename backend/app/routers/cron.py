"""Lets an outside scheduler trigger the daily alert job.

Why? Free hosts (like Render's free plan) put the app to sleep when nobody uses it,
so the built-in scheduler can't run. A free GitHub Actions workflow calls this
endpoint every weekday evening instead. The call also wakes the app up.

The caller must send the secret in the "X-Cron-Secret" header.
"""
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..services.alerts import run_daily_job

router = APIRouter(prefix="/cron", tags=["cron"])
settings = get_settings()


@router.post("/daily-alerts")
def daily_alerts(x_cron_secret: str = Header(default=""), db: Session = Depends(get_db)):
    if not settings.cron_secret:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    # compare_digest takes the same time whether the guess is close or not, so it can't be guessed bit by bit.
    if not secrets.compare_digest(x_cron_secret, settings.cron_secret):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Wrong cron secret")
    return run_daily_job(db)
