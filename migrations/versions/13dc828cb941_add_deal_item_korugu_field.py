"""add deal_item korugu field

Revision ID: 13dc828cb941
Revises: 5255038aa2b4
Create Date: 2026-09-24 23:07:16.567600

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '13dc828cb941'
down_revision = '5255038aa2b4'
branch_labels = None
depends_on = None


def upgrade():
    # NOT: autogenerate 4 trigram GIN index'ini yanlislikla "silinecek"
    # olarak isaretliyor (bilinen tekrarlayan false-positive) - elle
    # cikartildi, sadece gercek degisiklik kaldi.
    with op.batch_alter_table('deal_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('korugu', sa.String(length=50), nullable=True))


def downgrade():
    with op.batch_alter_table('deal_item', schema=None) as batch_op:
        batch_op.drop_column('korugu')
