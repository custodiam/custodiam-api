"""link materiales/vehiculos to ubicaciones catalog (E10 / PR2)

Revision ID: f1a2b3c4d5e6
Revises: e7a1b2c3d4e5
Create Date: 2026-05-30 11:00:00.000000

Engancha el inventario al catálogo de ubicaciones (transición suave):

- Añade ``ubicacion_base_id`` (``Uuid`` nullable, indexada) a ``materiales``
  y ``vehiculos`` con ``ForeignKey`` a ``ubicaciones.id`` y
  ``ondelete="RESTRICT"`` (no se borra una ubicación en uso; el service lo
  traduce a un 409 explícito antes de llegar al constraint).
- Relaja ``ubicacion_base`` (texto) de ``NOT NULL`` a nullable: pasa a ser
  una etiqueta legacy opcional; la referencia canónica es el FK.

Migración puramente estructural: no hay datos de inventario que poblar
(BD limpia). El downgrade asume que ``ubicacion_base`` está poblada en todas
las filas antes de re-imponer el ``NOT NULL`` (un operador real rellenaría
el texto desde el catálogo antes de bajar).
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "e7a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for tabla in ("materiales", "vehiculos"):
        op.add_column(
            tabla,
            sa.Column("ubicacion_base_id", sa.Uuid(), nullable=True),
        )
        op.create_index(
            op.f(f"ix_{tabla}_ubicacion_base_id"),
            tabla,
            ["ubicacion_base_id"],
        )
        op.create_foreign_key(
            f"fk_{tabla}_ubicacion_base_id_ubicaciones",
            tabla,
            "ubicaciones",
            ["ubicacion_base_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.alter_column(
            tabla,
            "ubicacion_base",
            existing_type=sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        )


def downgrade() -> None:
    for tabla in ("materiales", "vehiculos"):
        op.alter_column(
            tabla,
            "ubicacion_base",
            existing_type=sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        )
        op.drop_constraint(
            f"fk_{tabla}_ubicacion_base_id_ubicaciones",
            tabla,
            type_="foreignkey",
        )
        op.drop_index(op.f(f"ix_{tabla}_ubicacion_base_id"), tabla)
        op.drop_column(tabla, "ubicacion_base_id")
