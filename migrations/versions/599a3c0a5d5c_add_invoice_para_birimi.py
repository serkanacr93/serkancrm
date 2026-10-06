"""add_invoice_para_birimi

Revision ID: 599a3c0a5d5c
Revises: d212e6b833c5
Create Date: 2026-10-06 08:35:40.605591

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '599a3c0a5d5c'
down_revision = 'd212e6b833c5'
branch_labels = None
depends_on = None


def upgrade():
    # NOT: autogenerate'in trigram index false-positive'leri (ix_customer_*_trgm
    # - zaten mevcut, pg_trgm ops'u Alembic'in model karsilastirmasinda
    # tanimadigi icin "kaldirilacak" gibi gorunuyorlar) elle cikarildi.
    with op.batch_alter_table('invoice', schema=None) as batch_op:
        batch_op.add_column(sa.Column('para_birimi', sa.String(length=3), nullable=True))


def downgrade():
    with op.batch_alter_table('invoice', schema=None) as batch_op:
        batch_op.drop_column('para_birimi')
