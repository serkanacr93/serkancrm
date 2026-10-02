"""add_invoice_updated_by_log

Revision ID: 3a1e0e8257de
Revises: 3f49c8669114
Create Date: 2026-10-03 01:10:42.207330

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3a1e0e8257de'
down_revision = '3f49c8669114'
branch_labels = None
depends_on = None


def upgrade():
    # NOT: autogenerate'in yanlislikla "silinecek" isaretledigi 4 trigram
    # GIN index'i (bilinen tekrarlayan false-positive) elle cikartildi.
    # FK constraint'e acik isim verildi (unnamed batch-mode constraint
    # sorunu).
    with op.batch_alter_table('invoice', schema=None) as batch_op:
        batch_op.add_column(sa.Column('updated_by_user_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))
        batch_op.create_foreign_key('invoice_updated_by_user_id_fkey', 'user', ['updated_by_user_id'], ['id'])


def downgrade():
    with op.batch_alter_table('invoice', schema=None) as batch_op:
        batch_op.drop_constraint('invoice_updated_by_user_id_fkey', type_='foreignkey')
        batch_op.drop_column('updated_at')
        batch_op.drop_column('updated_by_user_id')
