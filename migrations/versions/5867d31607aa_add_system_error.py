"""add_system_error

Revision ID: 5867d31607aa
Revises: a7c3e9f12b45
Create Date: 2026-10-05 23:19:20.039451

NOT: system_error tablosu bu migration yazilmadan once db.create_all()
tarafindan (bilinen tekrarlayan yaris durumu) ZATEN olusturulmustu - DDL
burada TEKRAR calistirilmiyor, sadece Alembic surum gecmisine iz olarak
ekleniyor (flask db stamp ile isaretlenecek). Autogenerate'in trigram
index false-positive'leri (ix_customer_*_trgm) de elle cikarildi - bu
index'ler zaten mevcut ve dogru, pg_trgm ops'u Alembic'in model
karsilastirmasinda tanimadigi icin "kaldirilacak" gibi gorunuyorlar.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5867d31607aa'
down_revision = 'a7c3e9f12b45'
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    op.drop_table('system_error')
