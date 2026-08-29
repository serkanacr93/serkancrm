"""add deal_item numune_gorseli field

Revision ID: 5255038aa2b4
Revises: d9af8018830b
Create Date: 2026-08-29 20:51:47.400875

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5255038aa2b4'
down_revision = 'd9af8018830b'
branch_labels = None
depends_on = None


def upgrade():
    # NOT: autogenerate 4 trigram GIN index'ini yanlislikla "silinecek"
    # olarak isaretliyor (bilinen tekrarlayan false-positive - bkz. onceki
    # migration'lar) - elle cikartildi, sadece gercek degisiklik kaldi.
    with op.batch_alter_table('deal_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('numune_gorseli', sa.String(length=300), nullable=True))


def downgrade():
    with op.batch_alter_table('deal_item', schema=None) as batch_op:
        batch_op.drop_column('numune_gorseli')
