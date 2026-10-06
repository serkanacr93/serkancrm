"""add_teklif_yardimci_catalog

Revision ID: 42e3b89b4b63
Revises: 5867d31607aa
Create Date: 2026-10-06 00:00:00.000000

NOT: teklif_yardimci_config / kese_gramaj_katalog / doypack_katalog /
baski_fiyat_katalog tablolari bu migration yazilmadan once
db.create_all() tarafindan (bilinen tekrarlayan yaris durumu) ZATEN
olusturulmustu - DDL burada TEKRAR calistirilmiyor, sadece Alembic
surum gecmisine iz olarak ekleniyor (flask db stamp ile isaretlenecek).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '42e3b89b4b63'
down_revision = '5867d31607aa'
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    op.drop_table('baski_fiyat_katalog')
    op.drop_table('doypack_katalog')
    op.drop_table('kese_gramaj_katalog')
    op.drop_table('teklif_yardimci_config')
