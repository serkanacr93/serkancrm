"""add_company_settings_pdf_doviz_toggle

Revision ID: 81deea907371
Revises: 599a3c0a5d5c
Create Date: 2026-10-06 08:50:39.543455

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '81deea907371'
down_revision = '599a3c0a5d5c'
branch_labels = None
depends_on = None


def upgrade():
    # NOT: trigram index false-positive'leri elle cikarildi. server_default
    # eklendi - CompanySettings'te zaten 1 satir var (NOT NULL kolonu
    # varsayilan degersiz eklemek mevcut satirda hata verirdi).
    with op.batch_alter_table('company_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pdf_doviz_karsiligi_goster', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    with op.batch_alter_table('company_settings', schema=None) as batch_op:
        batch_op.drop_column('pdf_doviz_karsiligi_goster')
