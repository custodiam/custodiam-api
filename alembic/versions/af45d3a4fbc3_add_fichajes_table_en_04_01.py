"""add fichajes table (EN-04-01)

Revision ID: af45d3a4fbc3
Revises: 344062bfa502
Create Date: 2026-05-27 11:39:56.278883

Crea la tabla ``fichajes`` del módulo de Fichaje (Epic E04):

- Una fila por par (servicio, voluntario) — restricción UNIQUE.
- ``hora_salida`` nullable: ``NULL`` mientras el voluntario sigue en
  servicio.
- ``automatico`` distingue las salidas forzadas por el cierre del
  servicio (US-04-05) de las salidas explícitas del propio voluntario
  (CU-06).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "af45d3a4fbc3"
down_revision: str | None = "344062bfa502"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fichajes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("servicio_id", sa.Uuid(), nullable=False),
        sa.Column("voluntario_id", sa.Uuid(), nullable=False),
        sa.Column("hora_entrada", sa.DateTime(), nullable=False),
        sa.Column("hora_salida", sa.DateTime(), nullable=True),
        sa.Column("automatico", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["servicio_id"], ["servicios.id"]),
        sa.ForeignKeyConstraint(["voluntario_id"], ["voluntarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "servicio_id",
            "voluntario_id",
            name="uq_fichaje_servicio_voluntario",
        ),
    )
    op.create_index(
        op.f("ix_fichajes_servicio_id"),
        "fichajes",
        ["servicio_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_fichajes_voluntario_id"),
        "fichajes",
        ["voluntario_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_fichajes_voluntario_id"), table_name="fichajes")
    op.drop_index(op.f("ix_fichajes_servicio_id"), table_name="fichajes")
    op.drop_table("fichajes")
