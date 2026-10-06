"""add_takip_modu_atla

Revision ID: 8c5a972c96a9
Revises: 81deea907371
Create Date: 2026-10-06 21:11:54.087530

NOT: takip_modu_atla tablosu bu migration yazilmadan once db.create_all()
tarafindan (bilinen tekrarlayan yaris durumu) ZATEN olusturulmustu - DDL
burada TEKRAR calistirilmiyor, sadece Alembic surum gecmisine iz olarak
ekleniyor (flask db stamp ile isaretlenecek). Autogenerate'in trigram GIN
index "kaldirma" onerileri (customer.*_trgm) her zamanki false-positive -
manuel olarak cikarildi.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8c5a972c96a9'
down_revision = '81deea907371'
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    op.drop_table('takip_modu_atla')
