"""Admin-only endpoints. Shows role-based access control (RBAC) in action."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_admin
from ..models import Alert, Holding, User
from ..services.alerts import run_daily_job

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    """Usage numbers. Useful for your resume ("used by N people")."""
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    return {
        "users": db.scalar(select(func.count(User.id))),
        "users_with_portfolio": db.scalar(select(func.count(func.distinct(Holding.user_id)))),
        "new_users_7d": db.scalar(select(func.count(User.id)).where(User.created_at >= week_ago)),
        "holdings": db.scalar(select(func.count(Holding.id))),
        "alerts_total": db.scalar(select(func.count(Alert.id))),
        "alerts_sent_telegram": db.scalar(select(func.count(Alert.id)).where(Alert.sent_telegram.is_(True))),
    }


@router.post("/run-alerts")
def run_alerts(db: Session = Depends(get_db)):
    """Run the daily alert job for all users now."""
    return run_daily_job(db)
