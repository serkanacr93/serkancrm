"""teklif_formu_gorunumu

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-14 02:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('company_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('teklif_formu_gorunumu', sa.String(length=10), nullable=True))


def downgrade():
    with op.batch_alter_table('company_settings', schema=None) as batch_op:
        batch_op.drop_column('teklif_formu_gorunumu')
