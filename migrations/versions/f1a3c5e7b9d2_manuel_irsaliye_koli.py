"""manuel_irsaliye_koli

2026-10-28: manuel irsaliyeye koli adedi (yeni irsaliye PDF'indeki "Koli"
alani). SADECE nullable INTEGER kolon - eski kayitlarda NULL kalir.

Revision ID: f1a3c5e7b9d2
Revises: e6b1c9a7d2f4
Create Date: 2026-10-28 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f1a3c5e7b9d2'
down_revision = 'e6b1c9a7d2f4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('manual_irsaliye', schema=None) as batch_op:
        batch_op.add_column(sa.Column('koli_adedi', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('manual_irsaliye', schema=None) as batch_op:
        batch_op.drop_column('koli_adedi')
