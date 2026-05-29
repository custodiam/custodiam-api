"""add vehiculo_id to asignaciones_material and ternary target check (PR3)

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-05-29 23:11:00.000000

Segunda de las dos revisiones de PR3 (dotación fija de material a
vehículo, SP-09 opción A). Depende de ``a1b2c3d4e5f6``, que ya dejó el
valor ``DOTACION_VEHICULO`` confirmado en el tipo enum.

Cambios sobre ``asignaciones_material``:

- Añade la columna ``vehiculo_id`` (``Uuid`` nullable, indexada) +
  ``ForeignKey`` a ``vehiculos.id`` con ``ondelete="RESTRICT"`` (no se
  puede borrar un vehículo con dotación fija viva sin liberarla antes).
- Sustituye el ``CheckConstraint`` ``ck_asignacion_material_target`` del
  XOR binario voluntario/servicio por un **target ternario tipado**:
  exactamente uno de los tres destinos debe estar set.

El downgrade revierte en orden inverso (FK → check ternario → check
binario original → índice → columna). El valor del enum
``DOTACION_VEHICULO`` NO se elimina (ver nota en la revisión
``a1b2c3d4e5f6``: PostgreSQL no soporta DROP VALUE).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a1"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CHECK_NAME = "ck_asignacion_material_target"
_CHECK_TERNARIO = (
    "(voluntario_id IS NOT NULL)::int "
    "+ (servicio_id IS NOT NULL)::int "
    "+ (vehiculo_id IS NOT NULL)::int = 1"
)
_CHECK_BINARIO = "(voluntario_id IS NOT NULL) <> (servicio_id IS NOT NULL)"


def upgrade() -> None:
    op.add_column(
        "asignaciones_material",
        sa.Column("vehiculo_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        op.f("ix_asignaciones_material_vehiculo_id"),
        "asignaciones_material",
        ["vehiculo_id"],
        unique=False,
    )

    # El check binario sólo cuenta con voluntario/servicio; hay que
    # reemplazarlo por el ternario antes de que la columna vehiculo_id
    # pueda ser el único destino de una fila.
    op.drop_constraint(_CHECK_NAME, "asignaciones_material", type_="check")
    op.create_check_constraint(
        _CHECK_NAME, "asignaciones_material", _CHECK_TERNARIO
    )

    op.create_foreign_key(
        "fk_asignaciones_material_vehiculo_id_vehiculos",
        "asignaciones_material",
        "vehiculos",
        ["vehiculo_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    # AVISO OPERATIVO: el downgrade recrea el CHECK binario, que sólo
    # contempla voluntario/servicio. Cualquier fila de dotación fija viva
    # (``tipo=DOTACION_VEHICULO``, sólo ``vehiculo_id`` set) cuenta como 0
    # targets bajo el binario y hará fallar ``create_check_constraint`` con
    # ``CheckViolation``. Antes de bajar esta revisión hay que liberar o
    # migrar esas filas (p.ej. ``DELETE FROM asignaciones_material WHERE
    # tipo = 'DOTACION_VEHICULO'`` si se asume pérdida del histórico de
    # dotación).
    op.drop_constraint(
        "fk_asignaciones_material_vehiculo_id_vehiculos",
        "asignaciones_material",
        type_="foreignkey",
    )
    op.drop_constraint(_CHECK_NAME, "asignaciones_material", type_="check")
    op.create_check_constraint(
        _CHECK_NAME, "asignaciones_material", _CHECK_BINARIO
    )
    op.drop_index(
        op.f("ix_asignaciones_material_vehiculo_id"),
        table_name="asignaciones_material",
    )
    op.drop_column("asignaciones_material", "vehiculo_id")
