"""deal_ic_not

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-13 23:55:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('deal', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ic_not', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('deal', schema=None) as batch_op:
        batch_op.drop_column('ic_not')
