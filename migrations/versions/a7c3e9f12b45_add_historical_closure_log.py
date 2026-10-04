"""add_historical_closure_log

Revision ID: a7c3e9f12b45
Revises: 8e0c706806bb
Create Date: 2026-10-05 00:10:00.000000

NOT: historical_closure_log tablosu bu migration yazilmadan once
db.create_all() tarafindan (bilinen tekrarlayan yaris durumu) ZATEN
olusturulmustu - DDL burada TEKRAR calistirilmiyor, sadece Alembic
surum gecmisine iz olarak ekleniyor (flask db stamp ile isaretlenecek).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7c3e9f12b45'
down_revision = '8e0c706806bb'
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    op.drop_table('historical_closure_log')
