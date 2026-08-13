"""invoice user_id ownership field

Revision ID: d9af8018830b
Revises: c441cf2a07ea
Create Date: 2026-08-14 00:45:57.910703

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd9af8018830b'
down_revision = 'c441cf2a07ea'
branch_labels = None
depends_on = None


def upgrade():
    # NOT: Alembic autogenerate onceki migration'larda oldugu gibi
    # pg_trgm/GIN indexlerini kaldirilmis saniyordu - bu 4 drop_index
    # cagrisi kasitli olarak SILINDI. Sadece gercek degisiklik (Invoice.
    # user_id) kaldi.
    with op.batch_alter_table('invoice', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('invoice_user_id_fkey', 'user', ['user_id'], ['id'])


def downgrade():
    with op.batch_alter_table('invoice', schema=None) as batch_op:
        batch_op.drop_constraint('invoice_user_id_fkey', type_='foreignkey')
        batch_op.drop_column('user_id')
