from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..agent.graph import run_agent
from ..database import get_db
from ..deps import get_current_user
from ..models import User
from ..schemas import ChatIn, ChatOut

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatOut)
def chat(body: ChatIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    history = [m.model_dump() for m in body.history]
    return run_agent(db, user, body.message, history)
