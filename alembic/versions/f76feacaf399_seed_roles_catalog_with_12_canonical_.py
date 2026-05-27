"""seed roles catalog with 12 canonical roles (EN-02-05 hotfix)

Revision ID: f76feacaf399
Revises: 1d93d38841b2
Create Date: 2026-05-27 16:51:01.108470

Data migration que rellena la tabla ``roles`` con los 12 roles
canónicos del realm de Keycloak (los mismos del mapa
``ROLE_PERMISSIONS`` en ``app/core/permissions.py``).

Motivación
----------

Antes de este hotfix, la tabla ``roles`` quedaba vacía tras
``alembic upgrade head`` en un stack fresco. Consecuencia: ``GET
/api/v1/roles`` devolvía ``[]`` y ``POST /api/v1/voluntarios/{id}/roles``
devolvía 404 ``RolNoEncontrado`` siempre. El frente FE detectó el
gap al preparar ``seed-test-users.sh`` en ``custodiam-infra``.

Patrón aplicado
---------------

- ``op.bulk_insert(...)`` con ``uuid.uuid4()`` Python (no ``sa.text``)
  por lección de PR #11 (commit ``02709b3``): SQLAlchemy 2 + psycopg3
  no sustituyen ``TextClause`` en parámetros de ``bulk_insert``.
- ``permisos = None`` deliberadamente. La matriz canónica vive en
  ``app/core/permissions.py::ROLE_PERMISSIONS`` y el cliente la
  espeja como ``Permission`` enum
  (``custodiam-app/lib/infrastructure/auth/permissions.dart``) —
  lockstep ADR-013. Exponerla en la BD abriría puerta a divergencia.
- ``downgrade`` quirúrgico: ``DELETE FROM roles WHERE nombre IN (...)``
  con los nombres exactos seedeados, **NO** ``DELETE FROM roles`` a
  pelo, para no tocar roles custom que un operador hubiera añadido
  manualmente en producción.

Niveles
-------

El campo ``nivel`` solo se usa para ``order_by(Rol.nivel, Rol.nombre)``
en ``list_roles_catalogo``; sin comparaciones lógicas tipo
``>= cutoff``. Niveles duplicados (jefe_equipo/jefe_grupo en 3,
secretario/tesorero en 7) son válidos: el tiebreaker es el nombre.

Decisión: incluir ``voluntario_practicas`` aunque hoy comparta
permisos con ``voluntario`` (ver ``_TODOS_LOS_OPERATIVOS_BASE``).
Previsión: si emerge diferenciación operativa (UI etiqueta "En
prácticas", restricciones temporales, métricas de antigüedad), ya
existirá el rol en BD y solo habrá que cambiar la matriz de
permisos asociada. Coste cero (1 fila extra catálogo).
"""

import uuid
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f76feacaf399"
down_revision: str | None = "1d93d38841b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ROLES_CANONICOS = [
    ("voluntario_practicas", 1, "Voluntario nuevo en periodo de prueba"),
    ("voluntario", 2, "Voluntario operativo"),
    ("jefe_equipo", 3, "Jefe de un equipo en servicio"),
    ("jefe_grupo", 3, "Jefe de un grupo en servicio (alias operativo de jefe_equipo)"),
    ("jefe_seccion", 4, "Jefe de sección"),
    ("jefe_unidad", 5, "Jefe de unidad"),
    ("subjefe_agrupacion", 6, "Sub-jefe de la agrupación"),
    ("secretario", 7, "Secretario administrativo"),
    ("tesorero", 7, "Tesorero"),
    ("jefe_agrupacion", 8, "Jefe de la agrupación"),
    ("coordinador", 9, "Coordinador operativo (equivale a jefe_agrupacion)"),
    ("admin", 10, "Admin técnico de la aplicación"),
]


def upgrade() -> None:
    from sqlalchemy import Column, Integer, MetaData, String, Table
    from sqlalchemy import Uuid as SAUuid
    from sqlalchemy.dialects.postgresql import JSONB

    # Tabla ligera para el bulk_insert; no toca la metadata real de
    # SQLModel, solo describe las columnas necesarias para el insert.
    roles_table = Table(
        "roles",
        MetaData(),
        Column("id", SAUuid(), primary_key=True),
        Column("nombre", String(length=100)),
        Column("nivel", Integer()),
        Column("descripcion", String()),
        Column("permisos", JSONB()),
    )

    op.bulk_insert(
        roles_table,
        [
            {
                "id": uuid.uuid4(),
                "nombre": nombre,
                "nivel": nivel,
                "descripcion": descripcion,
                "permisos": None,
            }
            for nombre, nivel, descripcion in ROLES_CANONICOS
        ],
    )


def downgrade() -> None:
    nombres = ", ".join(f"'{nombre}'" for nombre, _, _ in ROLES_CANONICOS)
    op.execute(f"DELETE FROM roles WHERE nombre IN ({nombres})")
