"""teklif_pdf_yeni_tasarim

Revision ID: a1b2c3d4e5f6
Revises: e89c8ea63244
Create Date: 2026-10-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'e89c8ea63244'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('company_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('teklif_pdf_tasarim', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('teklif_sartlari', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('banka_adi', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('iban', sa.String(length=40), nullable=True))
    with op.batch_alter_table('deal', schema=None) as batch_op:
        batch_op.add_column(sa.Column('odeme_yontemi', sa.String(length=100), nullable=True))


def downgrade():
    with op.batch_alter_table('deal', schema=None) as batch_op:
        batch_op.drop_column('odeme_yontemi')
    with op.batch_alter_table('company_settings', schema=None) as batch_op:
        batch_op.drop_column('iban')
        batch_op.drop_column('banka_adi')
        batch_op.drop_column('teklif_sartlari')
        batch_op.drop_column('teklif_pdf_tasarim')
