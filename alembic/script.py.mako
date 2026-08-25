"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
# 'Text' se importa siempre a mano: autogenerate compone
# JSON().with_variant(postgresql.JSONB(astext_type=Text()), ...) para
# nuestras columnas JSONType pero nunca agrega este import solo — ya pasó
# tres veces antes de ponerlo aquí de forma permanente.
from sqlalchemy import Text
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
