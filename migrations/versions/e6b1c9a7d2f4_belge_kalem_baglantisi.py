"""belge_kalem_baglantisi

2026-10-27 (Veri akisi 2): fatura/irsaliye kalemlerini teklif kalemine,
manuel irsaliyeyi siparise baglar. SADECE nullable INTEGER kolon + index.
Bilerek FOREIGN KEY KONMADI: teklif duzenlenince (edit_deal) kalemler
silinip yeniden olusturuluyor - FK olsaydi faturasi kesilmis bir teklif
duzenlenemezdi. Eski kayitlarda NULL kalir (geriye donuk eslestirme yok).

Revision ID: e6b1c9a7d2f4
Revises: d8f3b2a61c07
Create Date: 2026-10-27 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e6b1c9a7d2f4'
down_revision = 'd8f3b2a61c07'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('invoice_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('deal_item_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_invoice_item_deal_item_id', ['deal_item_id'], unique=False)
    with op.batch_alter_table('manual_irsaliye', schema=None) as batch_op:
        batch_op.add_column(sa.Column('deal_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_manual_irsaliye_deal_id', ['deal_id'], unique=False)
    with op.batch_alter_table('manual_irsaliye_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('deal_item_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_manual_irsaliye_item_deal_item_id', ['deal_item_id'], unique=False)


def downgrade():
    with op.batch_alter_table('manual_irsaliye_item', schema=None) as batch_op:
        batch_op.drop_index('ix_manual_irsaliye_item_deal_item_id')
        batch_op.drop_column('deal_item_id')
    with op.batch_alter_table('manual_irsaliye', schema=None) as batch_op:
        batch_op.drop_index('ix_manual_irsaliye_deal_id')
        batch_op.drop_column('deal_id')
    with op.batch_alter_table('invoice_item', schema=None) as batch_op:
        batch_op.drop_index('ix_invoice_item_deal_item_id')
        batch_op.drop_column('deal_item_id')
