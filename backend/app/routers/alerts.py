from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Alert, Holding, User
from ..schemas import AlertOut
from ..services import telegram
from ..services.alerts import generate_alerts
from ..services.news import fetch_news

router = APIRouter(tags=["alerts & news"])


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(limit: int = 50, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(Alert).where(Alert.user_id == user.id).order_by(Alert.created_at.desc()).limit(min(limit, 200))
    ).all()


@router.post("/alerts/check")
def check_now(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Run the daily checks right now for the current user (handy for demos)."""
    new = generate_alerts(db, user)
    return {"new_alerts": len(new)}


@router.post("/alerts/read-all", status_code=204)
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(update(Alert).where(Alert.user_id == user.id).values(read=True))
    db.commit()


@router.post("/alerts/test-telegram")
def test_telegram(user: User = Depends(get_current_user)):
    if not telegram.telegram_enabled():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Telegram isn't set up on the server (TELEGRAM_BOT_TOKEN).")
    if not user.telegram_chat_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Add your Telegram chat ID in Settings first.")
    ok = telegram.send_message(user.telegram_chat_id, "✅ Portfolio Risk Copilot is connected. Alerts will arrive here.")
    if not ok:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Telegram didn't accept the message. Check the chat ID, "
                                                         "and make sure you pressed Start in the bot chat.")
    return {"sent": True}


@router.get("/news/{symbol}")
def news(symbol: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    h = db.scalar(select(Holding).where(Holding.user_id == user.id, Holding.symbol == symbol.upper()))
    if not h:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "You don't hold this stock")
    return [i.to_dict() for i in fetch_news(h.name or h.symbol, h.symbol)]
