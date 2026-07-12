"""add production_status_log table

Revision ID: 332857de1e8d
Revises: 124a7fddb559
Create Date: 2026-07-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '332857de1e8d'
down_revision = '124a7fddb559'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'production_status_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('production_id', sa.Integer(), nullable=False),
        sa.Column('from_status', sa.String(length=30), nullable=True),
        sa.Column('to_status', sa.String(length=30), nullable=False),
        sa.Column('changed_by_id', sa.Integer(), nullable=True),
        sa.Column('changed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['changed_by_id'], ['user.id']),
        sa.ForeignKeyConstraint(['production_id'], ['production.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_production_status_log_production_id'), 'production_status_log', ['production_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_production_status_log_production_id'), table_name='production_status_log')
    op.drop_table('production_status_log')
