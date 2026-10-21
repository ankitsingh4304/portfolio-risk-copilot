"""Sector names: one shared vocabulary (NSE's), whatever the source says."""
import pytest
from alembic import command
from sqlalchemy import select, text

from app.database import SessionLocal, _alembic_config
from app.models import Holding, User
from app.services import sectors, stocks_meta


@pytest.mark.parametrize("given,expected", [
    ("IT", "Information Technology"),
    ("information technology", "Information Technology"),
    ("Banking", "Financial Services"),
    ("FMCG", "Fast Moving Consumer Goods"),
    ("Pharma & Healthcare", "Healthcare"),
    ("Oil & Gas", "Oil Gas & Consumable Fuels"),
    ("Shipping", "Shipping"),  # unknown words are kept, not guessed
])
def test_normalize_sector(given, expected):
    assert sectors.normalize_sector(given) == expected


def test_yahoo_names_map_to_nse_names():
    assert sectors.from_yahoo("Technology", "Information Technology Services") == "Information Technology"
    assert sectors.from_yahoo("Consumer Cyclical", "Auto Manufacturers") == "Automobile and Auto Components"
    assert sectors.from_yahoo("Financial Services", "Banks - Regional") == "Financial Services"
    assert sectors.from_yahoo(None, None) is None


def test_find_sector_in_a_question():
    assert sectors.find_in_text("What if IT stocks fall 15%?") == "Information Technology"
    assert sectors.find_in_text("what if banks drop 20%") == "Financial Services"
    assert sectors.find_in_text("is it risky?") is None  # lowercase "it" is just a word


def test_stock_list_loads_from_csv_files():
    assert stocks_meta.count() > 100
    assert stocks_meta.lookup("INFY") == ("Infosys Ltd.", "Information Technology")
    assert stocks_meta.lookup("NIFTYBEES")[1] == "Index ETF"  # from extra_instruments.csv
    assert stocks_meta.symbol_from_name("ZOMATO LIMITED") == "ETERNAL"  # old name kept as an alias
    assert stocks_meta.lookup("NOTASTOCK") is None


def test_data_migration_renames_old_sector_labels(client):
    """Holdings saved with old labels ("IT") are renamed by migration 0002."""
    cfg = _alembic_config()
    command.downgrade(cfg, "0001_initial")  # 0002's downgrade changes nothing, so this is safe
    db = SessionLocal()
    user = User(email="migration@example.com", password_hash="x")
    db.add(user)
    db.commit()
    db.add_all([
        Holding(user_id=user.id, symbol="AAA", name="A", sector="IT", quantity=1, avg_price=1),
        Holding(user_id=user.id, symbol="BBB", name="B", sector="Banking", quantity=1, avg_price=1),
        Holding(user_id=user.id, symbol="CCC", name="C", sector="Shipping", quantity=1, avg_price=1),
    ])
    db.commit()

    command.upgrade(cfg, "head")

    got = dict(db.execute(select(Holding.symbol, Holding.sector).where(Holding.user_id == user.id)).all())
    assert got == {"AAA": "Information Technology", "BBB": "Financial Services", "CCC": "Shipping"}
    assert db.execute(text("select version_num from alembic_version")).scalar() == "0002_nse_sector_names"
    db.close()
