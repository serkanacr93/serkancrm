"""add customer owner_user_id field

Revision ID: 1f4f5e9cc8c1
Revises: 7c012693807b
Create Date: 2026-10-03 00:12:28.481707

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1f4f5e9cc8c1'
down_revision = '7c012693807b'
branch_labels = None
depends_on = None


def upgrade():
    # NOT: autogenerate'in yanlislikla "silinecek" isaretledigi 4 trigram
    # GIN index'i (bilinen tekrarlayan false-positive) elle cikartildi.
    # FK constraint'e acik isim verildi (unnamed batch-mode constraint
    # sorunu - bkz. d9af8018830b migration notu).
    with op.batch_alter_table('customer', schema=None) as batch_op:
        batch_op.add_column(sa.Column('owner_user_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_customer_owner_user_id'), ['owner_user_id'], unique=False)
        batch_op.create_foreign_key('customer_owner_user_id_fkey', 'user', ['owner_user_id'], ['id'])


def downgrade():
    with op.batch_alter_table('customer', schema=None) as batch_op:
        batch_op.drop_constraint('customer_owner_user_id_fkey', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_customer_owner_user_id'))
        batch_op.drop_column('owner_user_id')
