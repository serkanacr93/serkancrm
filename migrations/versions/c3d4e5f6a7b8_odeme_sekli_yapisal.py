"""odeme_sekli_yapisal

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-10-14 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('deal', schema=None) as batch_op:
        batch_op.add_column(sa.Column('odeme_vade_gun', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('pesinat_tipi', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('pesinat_deger', sa.Numeric(precision=14, scale=2), nullable=True))
        batch_op.add_column(sa.Column('bakiye_zamani', sa.String(length=30), nullable=True))


def downgrade():
    with op.batch_alter_table('deal', schema=None) as batch_op:
        batch_op.drop_column('bakiye_zamani')
        batch_op.drop_column('pesinat_deger')
        batch_op.drop_column('pesinat_tipi')
        batch_op.drop_column('odeme_vade_gun')
