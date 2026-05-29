"""add DOTACION_VEHICULO value to tipo_asignacion_material enum (PR3)

Revision ID: a1b2c3d4e5f6
Revises: 6ac94c20a63b
Create Date: 2026-05-29 23:10:00.000000

Primera de las dos revisiones de PR3 (dotación fija de material a
vehículo, SP-09 opción A).

Añade el valor ``DOTACION_VEHICULO`` al tipo enum PostgreSQL
``tipo_asignacion_material``. Va **sola en su propia revisión** porque
PostgreSQL no permite usar un valor de enum recién añadido dentro de la
misma transacción que lo crea (``ALTER TYPE ... ADD VALUE`` no es
visible hasta que la transacción confirma). La revisión siguiente
(``b2c3d4e5f6a1``) ya puede referenciar el valor con seguridad.

El label se añade en **MAYÚSCULA** (``DOTACION_VEHICULO``) para casar
con el resto de miembros del tipo, que se crearon con los ``.name`` del
``StrEnum`` (``PERSONAL``, ``PRESTAMO``, ``SERVICIO``) en la migración
``1d93d38841b2``. SQLAlchemy serializa los valores enum por ``.name``.

``IF NOT EXISTS`` hace la operación idempotente: re-aplicarla sobre una
BD que ya tiene el valor no falla.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "6ac94c20a63b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE tipo_asignacion_material "
        "ADD VALUE IF NOT EXISTS 'DOTACION_VEHICULO'"
    )


def downgrade() -> None:
    # PostgreSQL no soporta `ALTER TYPE ... DROP VALUE`. Eliminar un valor
    # de enum exigiría recrear el tipo entero (crear tipo nuevo, migrar las
    # columnas, eliminar el viejo), operación cara y arriesgada que no
    # aporta valor en un downgrade. El valor `DOTACION_VEHICULO` queda en
    # el tipo de forma inerte: si no hay filas que lo usen (la revisión B
    # las elimina al hacer downgrade) no causa ningún problema.
    pass
