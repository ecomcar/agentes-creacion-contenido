"""agregar marcas

Revision ID: 11b73f726b34
Revises: 354bc5f3ef32
Create Date: 2026-08-25 02:44:27.133174
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

revision: str = '11b73f726b34'
down_revision: str | None = '354bc5f3ef32'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('brands',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('default_audience', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('brand_voice', sa.Text(), nullable=True),
    sa.Column('forbidden_claims', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('competitors', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    # batch_alter_table en vez de add_column + create_foreign_key sueltos:
    # SQLite no soporta agregar una restricción de llave foránea a una
    # tabla ya existente con ALTER directo (sí lo soporta Postgres, pero no
    # hay que darlo por sentado sin probarlo). batch_alter_table usa la
    # estrategia de copiar-y-mover en SQLite y un ALTER normal en Postgres
    # — funciona igual en ambos motores. El nombre explícito de la
    # restricción también hace que el downgrade sea confiable, en vez de
    # depender de que Alembic adivine cuál es "la" foreign key de la tabla.
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('brand_id', sa.String(length=32), nullable=True))
        batch_op.create_foreign_key('fk_projects_brand_id', 'brands', ['brand_id'],
                                    ['id'], ondelete='SET NULL')


def downgrade() -> None:
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_constraint('fk_projects_brand_id', type_='foreignkey')
        batch_op.drop_column('brand_id')
    op.drop_table('brands')
