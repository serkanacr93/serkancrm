"""manual irsaliye + invoice deal_id nullable

Revision ID: c441cf2a07ea
Revises: 38e262d9d80a
Create Date: 2026-08-10 23:52:09.899733

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c441cf2a07ea'
down_revision = '38e262d9d80a'
branch_labels = None
depends_on = None


def upgrade():
    # NOT: Alembic autogenerate, onceki migration'larda oldugu gibi
    # pg_trgm/GIN indexlerini (model metadata'da izlenmedigi icin)
    # "kaldirilmis" saniyordu - bu 4 drop_index cagrisi kasitli olarak
    # SILINDI. Ayrica manual_irsaliye/manual_irsaliye_item tablolari icin
    # hicbir CREATE TABLE komutu YOK - bilinen db.create_all() / Alembic
    # yarisi geregi bu tablolar migrate calistirilmadan once app baslatilinca
    # zaten olusmustu (dogrulandi: inspect() ile Neon'da mevcut ve model
    # semasiyla birebir ayni). Sadece gercekten eksik olan invoice.deal_id
    # NOT NULL -> nullable degisikligi kaldi.
    with op.batch_alter_table('invoice', schema=None) as batch_op:
        batch_op.alter_column('deal_id',
               existing_type=sa.INTEGER(),
               nullable=True)


def downgrade():
    with op.batch_alter_table('invoice', schema=None) as batch_op:
        batch_op.alter_column('deal_id',
               existing_type=sa.INTEGER(),
               nullable=False)
