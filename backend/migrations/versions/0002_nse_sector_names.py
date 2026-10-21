"""Rename old sector labels to NSE's official industry names.

A *data* migration: no tables change, only values inside them.
Earlier versions used short labels like "IT" and "Banking". Now every part of the
app uses NSE's names ("Information Technology", "Financial Services"), so existing
holdings are updated to match. Without this, a user who uploaded before the change
would have "IT" while new uploads get "Information Technology", and a sector
scenario would miss half their IT stocks.

The mapping is copied here on purpose (not imported from the app), so this
migration keeps working even if the app's code changes later.

Revision ID: 0002_nse_sector_names
Revises: 0001_initial
Created: 2026-10-21
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_nse_sector_names"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

OLD_TO_NEW = {
    "IT": "Information Technology",
    "Banking": "Financial Services",
    "Energy": "Oil Gas & Consumable Fuels",
    "FMCG": "Fast Moving Consumer Goods",
    "Consumer": "Consumer Durables",
    "Pharma & Healthcare": "Healthcare",
    "Auto": "Automobile and Auto Components",
    "Telecom": "Telecommunication",
    "Infrastructure": "Construction",
    "Cement": "Construction Materials",
    "Metals": "Metals & Mining",
    "Gold": "Gold ETF",
}


def upgrade():
    holdings = sa.table("holdings", sa.column("sector", sa.String))
    for old, new in OLD_TO_NEW.items():
        op.execute(holdings.update().where(holdings.c.sector == old).values(sector=new))


def downgrade():
    # Going back is safe to skip: the old labels were only shorter names for the same sectors.
    pass
