"""irsaliye_fatura_esitleme

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-14 01:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('invoice', schema=None) as batch_op:
        batch_op.add_column(sa.Column('muhasebeye_gonderildi', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('muhasebeye_gonderilme_tarihi', sa.DateTime(), nullable=True))

    op.create_table(
        'irsaliye_degisiklik_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('irsaliye_id', sa.Integer(), sa.ForeignKey('manual_irsaliye.id'), nullable=False),
        sa.Column('invoice_id', sa.Integer(), sa.ForeignKey('invoice.id'), nullable=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('tarih', sa.DateTime(), nullable=True),
        sa.Column('aciklama', sa.Text(), nullable=True),
        sa.Column('onceki_json', sa.Text(), nullable=True),
        sa.Column('sonraki_json', sa.Text(), nullable=True),
    )
    op.create_index('ix_irsaliye_degisiklik_log_irsaliye_id', 'irsaliye_degisiklik_log', ['irsaliye_id'])


def downgrade():
    op.drop_index('ix_irsaliye_degisiklik_log_irsaliye_id', table_name='irsaliye_degisiklik_log')
    op.drop_table('irsaliye_degisiklik_log')
    with op.batch_alter_table('invoice', schema=None) as batch_op:
        batch_op.drop_column('muhasebeye_gonderilme_tarihi')
        batch_op.drop_column('muhasebeye_gonderildi')
