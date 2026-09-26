"""add daily production output and photo tables

Revision ID: 7c012693807b
Revises: 13dc828cb941
Create Date: 2026-09-24 23:21:38.758752

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7c012693807b'
down_revision = '13dc828cb941'
branch_labels = None
depends_on = None


def upgrade():
    # NOT: daily_production_output/daily_production_photo tablolari bu
    # migration calistirilmadan ONCE zaten db.create_all() ile olusmustu
    # (bilinen tekrarlayan race - bkz. onceki migration'lar), inspect() ile
    # model semasiyla birebir ayni oldugu dogrulandi. autogenerate'in
    # yanlislikla "silinecek" isaretledigi 4 trigram GIN index de (bilinen
    # tekrarlayan false-positive) elle cikartildi - bu migration'da
    # GERCEKTEN yapilacak bir sema degisikligi yok.
    pass


def downgrade():
    pass
