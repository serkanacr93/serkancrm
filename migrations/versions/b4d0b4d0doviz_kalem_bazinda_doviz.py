"""kalem_bazinda_doviz_asama1

Revision ID: b4d0b4d0doviz
Revises: f6a7b8c9d0e1
Create Date: 2026-10-14 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b4d0b4d0doviz'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('deal', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kur_usd', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('kur_eur', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('kur_tarihi', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('kur_turu', sa.String(length=10), nullable=True))
    with op.batch_alter_table('deal_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('para_birimi', sa.String(length=3), nullable=True))


def downgrade():
    with op.batch_alter_table('deal_item', schema=None) as batch_op:
        batch_op.drop_column('para_birimi')
    with op.batch_alter_table('deal', schema=None) as batch_op:
        batch_op.drop_column('kur_turu')
        batch_op.drop_column('kur_tarihi')
        batch_op.drop_column('kur_eur')
        batch_op.drop_column('kur_usd')
