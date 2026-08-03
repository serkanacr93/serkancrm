"""add manual_tedarik_entry table

Revision ID: 9f2a4e7c1d3b
Revises: 5819eb2f180b
Create Date: 2026-08-04 00:00:00.000000

NOT: Bu tablo create_app() icindeki db.create_all() tarafindan Alembic'ten
once otomatik olusturuldugu icin (bilinen db.create_all()/Flask-Migrate
cakismasi - bkz. YAPILACAKLAR.md), bu migration `flask db stamp head` ile
gercek DDL calistirilmadan isaretlendi. Sifirdan bir ortamda (create_all()
calismadan once) uygulanirsa asagidaki upgrade() tabloyu dogru sekilde
olusturur.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9f2a4e7c1d3b'
down_revision = '5819eb2f180b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'manual_tedarik_entry',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('customer_name', sa.String(length=200), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=True),
        sa.Column('urun', sa.String(length=200), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('unit', sa.String(length=20), nullable=True),
        sa.Column('delivery_date', sa.Date(), nullable=True),
        sa.Column('durum', sa.String(length=20), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('manual_tedarik_entry')
