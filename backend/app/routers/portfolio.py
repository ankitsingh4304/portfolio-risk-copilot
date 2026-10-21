from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Holding, User
from ..schemas import HoldingIn, HoldingOut, UploadOut
from ..services import stocks_meta
from ..services.csv_parser import ParseError, parse_holdings_file
from ..services.excel_report import build_excel
from ..services.portfolio_data import NoHoldingsError, build_snapshot, risk_report
from ..services.prices import lookup_sector_online
from ..services.sectors import normalize_sector

router = APIRouter(prefix="/portfolio", tags=["portfolio"])
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def _name_and_sector(symbol: str, name: str = "", sector: str | None = None) -> tuple[str, str]:
    """Sector, in order: NSE list -> the upload's own sector column -> Yahoo -> "Other".

    All sector names are converted to NSE's names, so "IT" and "Technology" both become
    "Information Technology" and scenarios catch every stock in a sector.
    """
    known = stocks_meta.lookup(symbol)
    final_name = (known[0] if known else None) or name or symbol
    final_sector = (
        (known[1] if known else None)
        or normalize_sector(sector)
        or lookup_sector_online(symbol)
        or "Other"
    )
    return final_name[:200], final_sector[:80]


@router.get("/holdings", response_model=list[HoldingOut])
def list_holdings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Holding).where(Holding.user_id == user.id).order_by(Holding.symbol)).all()


@router.post("/upload", response_model=UploadOut)
async def upload(
    file: UploadFile = File(...),
    replace: bool = Query(True, description="Replace existing holdings (true) or merge into them (false)"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large (max 5 MB)")
    try:
        parsed = parse_holdings_file(content, file.filename or "upload.csv")
    except ParseError as exc:
        raise HTTPException(422, str(exc))

    if replace:
        db.execute(delete(Holding).where(Holding.user_id == user.id))
    existing = {h.symbol: h for h in db.scalars(select(Holding).where(Holding.user_id == user.id))}
    for p in parsed.holdings:
        name, sector = _name_and_sector(p.symbol, p.name, p.sector)
        if p.symbol in existing:  # merge: combine quantities
            h = existing[p.symbol]
            total = h.quantity + p.quantity
            h.avg_price = (h.avg_price * h.quantity + p.avg_price * p.quantity) / total
            h.quantity = total
        else:
            db.add(Holding(user_id=user.id, symbol=p.symbol, name=name, sector=sector,
                           quantity=p.quantity, avg_price=p.avg_price))
    try:
        db.commit()
    except IntegrityError:  # e.g. the same file uploaded twice at the same moment
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Another upload was saving at the same time. Please try again.")
    holdings = db.scalars(select(Holding).where(Holding.user_id == user.id).order_by(Holding.symbol)).all()
    return UploadOut(detected_format=parsed.detected_format, imported=len(parsed.holdings),
                     warnings=parsed.warnings, columns_used=parsed.columns_used, holdings=holdings)


@router.post("/holdings", response_model=HoldingOut, status_code=201)
def add_holding(body: HoldingIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if db.scalar(select(Holding).where(Holding.user_id == user.id, Holding.symbol == body.symbol)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"You already hold {body.symbol}. Edit it instead.")
    name, sector = _name_and_sector(body.symbol, sector=body.sector)
    h = Holding(user_id=user.id, symbol=body.symbol, name=name, sector=sector,
                quantity=body.quantity, avg_price=body.avg_price)
    db.add(h)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"You already hold {body.symbol}. Edit it instead.")
    return h


@router.put("/holdings/{holding_id}", response_model=HoldingOut)
def edit_holding(holding_id: int, body: HoldingIn, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    h = db.get(Holding, holding_id)
    if not h or h.user_id != user.id:  # never let one user touch another user's data
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Holding not found")
    h.quantity, h.avg_price = body.quantity, body.avg_price
    if body.sector:
        h.sector = normalize_sector(body.sector)
    db.commit()
    return h


@router.delete("/holdings/{holding_id}", status_code=204)
def delete_holding(holding_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    h = db.get(Holding, holding_id)
    if not h or h.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Holding not found")
    db.delete(h)
    db.commit()


@router.get("/risk")
def get_risk(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Full risk report: summary metrics, per-stock risk, correlations, history for charts."""
    try:
        return risk_report(build_snapshot(db, user))
    except NoHoldingsError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))


@router.get("/report.xlsx", response_class=Response)
def excel_report(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Download the full risk report as an Excel file."""
    try:
        content = build_excel(build_snapshot(db, user))
    except NoHoldingsError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    filename = f"risk-report-{date.today().isoformat()}.xlsx"
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
