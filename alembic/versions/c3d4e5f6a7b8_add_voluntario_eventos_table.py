"""add voluntario_eventos table (EN-02-04 / US-02-06)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-28 12:00:00.000000

Crea la tabla ``voluntario_eventos`` y el enum ``tipo_evento_voluntario``
que cierran el módulo de historial del voluntario (Epic E02 / EN-02-04).

El índice compuesto ``(voluntario_id, created_at DESC)`` se crea
explícitamente para que las consultas paginadas del historial
(``GET /voluntarios/me/historial``) recorran las filas más recientes
del voluntario sin necesidad de sort en memoria.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "voluntario_eventos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("voluntario_id", sa.Uuid(), nullable=False),
        sa.Column(
            "tipo_evento",
            sa.Enum(
                "ALTA",
                "BAJA",
                "ANONIMIZACION",
                "CAMBIO_ROL_ASIGNADO",
                "CAMBIO_ROL_REVOCADO",
                "FICHAJE_ENTRADA",
                "FICHAJE_SALIDA",
                "INSCRIPCION_SERVICIO",
                "BAJA_INSCRIPCION",
                "ASIGNACION_MATERIAL",
                "DEVOLUCION_MATERIAL",
                name="tipo_evento_voluntario",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "actor_keycloak_id",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["voluntario_id"], ["voluntarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_voluntario_eventos_voluntario_id"),
        "voluntario_eventos",
        ["voluntario_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_voluntario_eventos_actor_keycloak_id"),
        "voluntario_eventos",
        ["actor_keycloak_id"],
        unique=False,
    )
    # Índice compuesto para el paginado por voluntario + recencia (DESC):
    # la cláusula ORDER BY del repository usa exactamente este orden.
    op.create_index(
        "ix_voluntario_eventos_voluntario_created_at_desc",
        "voluntario_eventos",
        ["voluntario_id", sa.text("created_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_voluntario_eventos_voluntario_created_at_desc",
        table_name="voluntario_eventos",
    )
    op.drop_index(
        op.f("ix_voluntario_eventos_actor_keycloak_id"),
        table_name="voluntario_eventos",
    )
    op.drop_index(
        op.f("ix_voluntario_eventos_voluntario_id"),
        table_name="voluntario_eventos",
    )
    op.drop_table("voluntario_eventos")
    sa.Enum(name="tipo_evento_voluntario").drop(op.get_bind(), checkfirst=True)
