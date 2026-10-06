"""add_production_plan_order

Revision ID: d212e6b833c5
Revises: 42e3b89b4b63
Create Date: 2026-10-06 03:30:00.000000

NOT: production_plan_order tablosu bu migration yazilmadan once
db.create_all() tarafindan (bilinen tekrarlayan yaris durumu) ZATEN
olusturulmustu - DDL burada TEKRAR calistirilmiyor, sadece Alembic
surum gecmisine iz olarak ekleniyor (flask db stamp ile isaretlenecek).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd212e6b833c5'
down_revision = '42e3b89b4b63'
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    op.drop_table('production_plan_order')
