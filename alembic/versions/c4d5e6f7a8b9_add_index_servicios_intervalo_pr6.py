"""add index on servicios(fecha_inicio, fecha_fin) for overlap query (PR6)

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a1
Create Date: 2026-05-29 23:55:00.000000

Soporte de la detección de solape temporal de recursos (PR6 / Política A).
La query de no-solape (``find_servicios_solapados_vehiculo`` /
``find_solapes_material`` en ``app/repositories/inventario.py``) une
``asignaciones_*`` con ``servicios`` y filtra por
``fecha_inicio < fin AND inicio < fecha_fin`` sobre los servicios que
reservan (PUBLICADO / ACTIVO) con ``fecha_fin`` no NULL. Un índice
compuesto en ``servicios(fecha_inicio, fecha_fin)`` acota el rango sin
escaneo secuencial conforme crece el histórico de servicios.

No toca datos ni columnas: sólo añade el índice. upgrade/downgrade
simétricos.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: str | None = "b2c3d4e5f6a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "ix_servicios_fecha_inicio_fecha_fin"


def upgrade() -> None:
    op.create_index(
        _INDEX_NAME,
        "servicios",
        ["fecha_inicio", "fecha_fin"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="servicios")
