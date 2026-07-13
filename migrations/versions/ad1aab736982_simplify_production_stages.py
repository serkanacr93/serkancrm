"""simplify production stages - drop production_status_log, migrate beklemede -> uretimde

Revision ID: ad1aab736982
Revises: 6460f295f74b
Create Date: 2026-07-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ad1aab736982'
down_revision = '6460f295f74b'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE production SET status = 'uretimde' WHERE status = 'beklemede'")
    op.drop_index('ix_production_status_log_production_id', table_name='production_status_log')
    op.drop_table('production_status_log')


def downgrade():
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
    op.create_index('ix_production_status_log_production_id', 'production_status_log', ['production_id'], unique=False)
    op.execute("UPDATE production SET status = 'beklemede' WHERE status = 'uretimde'")
