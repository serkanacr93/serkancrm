"""add_takip_modu_models

Revision ID: 8e0c706806bb
Revises: f3a8b1c9d201
Create Date: 2026-10-04 23:38:27.194377

NOT: daily_outreach_count ve payment_reminder tablolari bu migration
yazilmadan once db.create_all() tarafindan (bilinen tekrarlayan yaris
durumu) ZATEN olusturulmustu - bu yuzden autogenerate onlar icin hic
DDL uretmedi, sadece daily_report.tekrar_ara_tarihi kolonu eksikti.
4 trigram GIN index'i (bilinen tekrarlayan false-positive) elle
cikartildi.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8e0c706806bb'
down_revision = 'f3a8b1c9d201'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('daily_report', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tekrar_ara_tarihi', sa.Date(), nullable=True))
        batch_op.create_index(batch_op.f('ix_daily_report_tekrar_ara_tarihi'), ['tekrar_ara_tarihi'], unique=False)


def downgrade():
    with op.batch_alter_table('daily_report', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_daily_report_tekrar_ara_tarihi'))
        batch_op.drop_column('tekrar_ara_tarihi')
