"""is_emri_koli_kese

2026-10-26 (Is Emri yatay tasarim): SADECE nullable kolon ekleme.
- deal_item.kese_gramaj: secilen kese numarasi (100/250/.../2000 gr) -
  KeseGramajKatalog.gramaj degerinin kopyasi, FK DEGIL (katalog degisse de
  eski teklif/is emri bozulmasin).
- deal_item.koli_tipi: 'baskili' / 'baskisiz' - NULL = firma baskili kabul.
- customer.varsayilan_koli: yeni kalemlere on-secili gelen koli tipi.
- daily_production_output.production_item_id: Gunluk Uretim girisini
  is emrinin TEK BIR KALEMINE baglamak icin (opsiyonel).

Revision ID: d8f3b2a61c07
Revises: c7e2a9d41b05
Create Date: 2026-10-26 13:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd8f3b2a61c07'
down_revision = 'c7e2a9d41b05'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('deal_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kese_gramaj', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('koli_tipi', sa.String(length=20), nullable=True))
    with op.batch_alter_table('customer', schema=None) as batch_op:
        batch_op.add_column(sa.Column('varsayilan_koli', sa.String(length=20), nullable=True))
    with op.batch_alter_table('daily_production_output', schema=None) as batch_op:
        batch_op.add_column(sa.Column('production_item_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_daily_production_output_production_item_id', ['production_item_id'], unique=False)
        batch_op.create_foreign_key('fk_dpo_production_item_id', 'production_item', ['production_item_id'], ['id'])


def downgrade():
    with op.batch_alter_table('daily_production_output', schema=None) as batch_op:
        batch_op.drop_constraint('fk_dpo_production_item_id', type_='foreignkey')
        batch_op.drop_index('ix_daily_production_output_production_item_id')
        batch_op.drop_column('production_item_id')
    with op.batch_alter_table('customer', schema=None) as batch_op:
        batch_op.drop_column('varsayilan_koli')
    with op.batch_alter_table('deal_item', schema=None) as batch_op:
        batch_op.drop_column('koli_tipi')
        batch_op.drop_column('kese_gramaj')
