"""bilgi_eksik_ve_kagit_cinsi

Revision ID: e89c8ea63244
Revises: 8c5a972c96a9
Create Date: 2026-10-07 01:39:20.781816

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e89c8ea63244'
down_revision = '8c5a972c96a9'
branch_labels = None
depends_on = None


def upgrade():
    # trigram GIN index "kaldirma" onerileri autogenerate'in her
    # calismasinda cikan bilinen false-positive - manuel olarak cikarildi,
    # sadece gercek ADD COLUMN'lar uygulaniyor.
    op.add_column('customer', sa.Column('bilgi_eksik', sa.Boolean(), nullable=True))
    op.add_column('daily_production_output', sa.Column('kagit_cinsi', sa.String(length=30), nullable=True))


def downgrade():
    op.drop_column('daily_production_output', 'kagit_cinsi')
    op.drop_column('customer', 'bilgi_eksik')
