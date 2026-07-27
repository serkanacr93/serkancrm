"""add company_settings table

Revision ID: 0d1d767e7447
Revises: 5b0397d38754
Create Date: 2026-07-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0d1d767e7447'
down_revision = '5b0397d38754'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'company_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_name', sa.String(length=200), nullable=False),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('fax', sa.String(length=50), nullable=True),
        sa.Column('email', sa.String(length=120), nullable=True),
        sa.Column('website', sa.String(length=200), nullable=True),
        sa.Column('tax_office', sa.String(length=100), nullable=True),
        sa.Column('tax_id', sa.String(length=20), nullable=True),
        sa.Column('logo_data', sa.LargeBinary(), nullable=True),
        sa.Column('logo_mimetype', sa.String(length=50), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('company_settings')
