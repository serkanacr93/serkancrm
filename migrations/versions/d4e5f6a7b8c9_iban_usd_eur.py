"""iban_usd_eur

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-10-14 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('company_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('iban_usd', sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column('iban_eur', sa.String(length=40), nullable=True))


def downgrade():
    with op.batch_alter_table('company_settings', schema=None) as batch_op:
        batch_op.drop_column('iban_eur')
        batch_op.drop_column('iban_usd')
