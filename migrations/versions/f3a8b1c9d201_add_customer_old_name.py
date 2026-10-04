"""add_customer_old_name

Revision ID: f3a8b1c9d201
Revises: c25da7082d6d
Create Date: 2026-10-04 12:00:00.000000

NOT: customer_old_name tablosu bu migration yazilmadan once db.create_all()
tarafindan (bilinen tekrarlayan yaris durumu - arka planda birden fazla
kez baslatilan gelistirme sunucusu) ZATEN olusturulmustu. DDL burada
TEKRAR calistirilmiyor (zaten var olan tabloyu bozar/hata verir) -
sadece Alembic'in surum gecmisine iz olarak ekleniyor (flask db stamp
ile isaretlenecek).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f3a8b1c9d201'
down_revision = 'c25da7082d6d'
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    op.drop_table('customer_old_name')
