"""add ubicaciones catalog table (E10 / PR2)

Revision ID: e7a1b2c3d4e5
Revises: c4d5e6f7a8b9
Create Date: 2026-05-30 10:00:00.000000

Crea el catálogo ``ubicaciones`` que promueve el ``ubicacion_base`` de texto
libre de ``materiales`` / ``vehiculos`` a una entidad seleccionable:

- ``nombre`` único (evita duplicados desde el alta del picker).
- ``descripcion`` opcional.
- ``lat`` / ``lng`` ``Float`` nullable: coordenadas opcionales que habilitan
  la futura capa de mapas (ADR-030) sin re-migrar. Los registros nacen a
  ``NULL`` (no ``0.0``); la validación de rango y "ambos o ninguno" vive en
  Pydantic, no como CHECK en BD (mismo criterio que el geo de ``servicios``).

Sin FK desde ``materiales`` / ``vehiculos`` todavía: el enganche se hace en
una migración posterior (transición suave). Esta migración es puramente
estructural — no hay datos de ubicaciones que migrar.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7a1b2c3d4e5"
down_revision: str | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ubicaciones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "nombre",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column(
            "descripcion",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
        ),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nombre"),
    )


def downgrade() -> None:
    op.drop_table("ubicaciones")
