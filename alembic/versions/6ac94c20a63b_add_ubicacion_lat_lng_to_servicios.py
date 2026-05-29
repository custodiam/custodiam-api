"""add ubicacion_lat/lng to servicios

Revision ID: 6ac94c20a63b
Revises: c3d4e5f6a7b8
Create Date: 2026-05-29 21:59:53.625672

Añade las coordenadas geográficas opcionales al servicio (PR2-geo, SP-09):

- ``ubicacion_lat`` y ``ubicacion_lng`` como ``Float`` nullable, embebidas
  en ``servicios`` junto al campo ``ubicacion`` (etiqueta humana, que se
  mantiene). Sin tabla de ubicaciones ni FK: PR2-catálogo es independiente.

Los servicios históricos quedan a ``NULL`` (no ``0.0``). La validación de
rango y la regla "ambos o ninguno" viven en Pydantic, no como CHECK en BD.
El índice parcial de proximidad se difiere a un enabler posterior.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6ac94c20a63b"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "servicios",
        sa.Column("ubicacion_lat", sa.Float(), nullable=True),
    )
    op.add_column(
        "servicios",
        sa.Column("ubicacion_lng", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("servicios", "ubicacion_lng")
    op.drop_column("servicios", "ubicacion_lat")
