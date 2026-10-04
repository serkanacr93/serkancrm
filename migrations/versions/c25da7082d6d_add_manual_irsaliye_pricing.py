"""add_manual_irsaliye_pricing

Revision ID: c25da7082d6d
Revises: 3a1e0e8257de
Create Date: 2026-10-04 02:15:01.368177

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c25da7082d6d'
down_revision = '3a1e0e8257de'
branch_labels = None
depends_on = None


def upgrade():
    # NOT: autogenerate'in yanlislikla "silinecek" isaretledigi 4 trigram
    # GIN index'i (bilinen tekrarlayan false-positive) elle cikartildi.
    # FK constraint'e acik isim verildi (unnamed batch-mode constraint
    # sorunu).
    with op.batch_alter_table('manual_irsaliye', schema=None) as batch_op:
        batch_op.add_column(sa.Column('vat_rate', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('invoice_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('manual_irsaliye_invoice_id_fkey', 'invoice', ['invoice_id'], ['id'])

    with op.batch_alter_table('manual_irsaliye_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('unit_price', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('manual_irsaliye_item', schema=None) as batch_op:
        batch_op.drop_column('unit_price')

    with op.batch_alter_table('manual_irsaliye', schema=None) as batch_op:
        batch_op.drop_constraint('manual_irsaliye_invoice_id_fkey', type_='foreignkey')
        batch_op.drop_column('invoice_id')
        batch_op.drop_column('vat_rate')
