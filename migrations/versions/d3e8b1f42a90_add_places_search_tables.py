"""Add places search config and log tables

Revision ID: d3e8b1f42a90
Revises: a7f3c9d2e841
Create Date: 2026-07-07 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd3e8b1f42a90'
down_revision = 'a7f3c9d2e841'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('places_search_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('last_combo_index', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('places_search_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('run_at', sa.DateTime(), nullable=False),
        sa.Column('city', sa.String(length=100), nullable=True),
        sa.Column('sector', sa.String(length=50), nullable=True),
        sa.Column('search_query', sa.String(length=300), nullable=True),
        sa.Column('request_count', sa.Integer(), nullable=True),
        sa.Column('results_found', sa.Integer(), nullable=True),
        sa.Column('new_companies', sa.Integer(), nullable=True),
        sa.Column('triggered_by', sa.String(length=20), nullable=True),
        sa.Column('error', sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('places_search_log')
    op.drop_table('places_search_config')
