"""add_daily_production_output_production_id

Revision ID: 3f49c8669114
Revises: 1f4f5e9cc8c1
Create Date: 2026-10-03 00:51:31.655617

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3f49c8669114'
down_revision = '1f4f5e9cc8c1'
branch_labels = None
depends_on = None


def upgrade():
    # NOT: autogenerate'in yanlislikla "silinecek" isaretledigi 4 trigram
    # GIN index'i (bilinen tekrarlayan false-positive) elle cikartildi.
    # FK constraint'e acik isim verildi (unnamed batch-mode constraint
    # sorunu).
    with op.batch_alter_table('daily_production_output', schema=None) as batch_op:
        batch_op.add_column(sa.Column('production_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_daily_production_output_production_id'), ['production_id'], unique=False)
        batch_op.create_foreign_key('daily_production_output_production_id_fkey', 'production', ['production_id'], ['id'])


def downgrade():
    with op.batch_alter_table('daily_production_output', schema=None) as batch_op:
        batch_op.drop_constraint('daily_production_output_production_id_fkey', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_daily_production_output_production_id'))
        batch_op.drop_column('production_id')
