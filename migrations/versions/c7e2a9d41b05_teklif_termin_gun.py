"""teklif_termin_gun

Revision ID: c7e2a9d41b05
Revises: b4d0b4d0doviz
Create Date: 2026-10-22 22:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c7e2a9d41b05'
down_revision = 'b4d0b4d0doviz'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('deal_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('termin_gun', sa.Integer(), nullable=True))
    with op.batch_alter_table('deal', schema=None) as batch_op:
        batch_op.add_column(sa.Column('varsayilan_termin_gun', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('deal', schema=None) as batch_op:
        batch_op.drop_column('varsayilan_termin_gun')
    with op.batch_alter_table('deal_item', schema=None) as batch_op:
        batch_op.drop_column('termin_gun')
