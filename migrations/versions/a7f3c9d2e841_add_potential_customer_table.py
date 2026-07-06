"""Add potential customer table

Revision ID: a7f3c9d2e841
Revises: 290123af7c0c
Create Date: 2026-07-06 02:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7f3c9d2e841'
down_revision = '290123af7c0c'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('potential_customer',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_name', sa.String(length=200), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('city', sa.String(length=100), nullable=True),
        sa.Column('sector', sa.String(length=50), nullable=True),
        sa.Column('interested_products', sa.String(length=500), nullable=True),
        sa.Column('source', sa.String(length=20), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('converted_customer_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['converted_customer_id'], ['customer.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('potential_customer')
