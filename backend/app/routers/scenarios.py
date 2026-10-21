from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import User
from ..schemas import CustomShockIn, HistoricalIn, MarketShockIn, SectorShockIn
from ..services import scenarios as sc
from ..services.portfolio_data import NoHoldingsError, build_snapshot

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


def _snapshot(db, user):
    try:
        return build_snapshot(db, user)
    except NoHoldingsError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))


def _run(fn, *args):
    try:
        return fn(*args)
    except sc.ScenarioError as exc:
        raise HTTPException(422, str(exc))


@router.get("/events")
def list_events():
    return [
        {"key": e.key, "name": e.name, "start": e.start, "end": e.end, "description": e.description}
        for e in sc.HISTORICAL_EVENTS.values()
    ]


@router.post("/sector")
def sector(body: SectorShockIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _run(sc.sector_shock, _snapshot(db, user), body.sector, body.drop_pct, body.knock_on)


@router.post("/market")
def market(body: MarketShockIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _run(sc.market_shock, _snapshot(db, user), body.drop_pct)


@router.post("/custom")
def custom(body: CustomShockIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _run(sc.custom_shock, _snapshot(db, user), body.shocks)


@router.post("/historical")
def historical(body: HistoricalIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _run(sc.historical_replay, _snapshot(db, user), body.event)
