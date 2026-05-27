"""add materiales, vehiculos and asignaciones tables (EN-05-01)

Revision ID: 1d93d38841b2
Revises: af45d3a4fbc3
Create Date: 2026-05-27 13:26:49.398223

Crea las tablas del módulo de Inventario (Epic E05):

- ``materiales``: material/equipamiento del inventario (incluye
  ``tipo_material`` enum personal/prestable/servicio).
- ``vehiculos``: vehículos de la agrupación (tabla separada por
  divergencia de campos y por corte distinto en el RBAC; comparte
  el enum ``estado_inventario`` con materiales).
- ``asignaciones_material`` y ``asignaciones_vehiculo``: relaciones
  N:M con voluntario (solo material) y servicio.

El enum ``estado_inventario`` se crea **una sola vez** explícitamente
porque dos columnas lo referencian (``materiales.estado`` y
``vehiculos.estado``) — si se dejara a SQLAlchemy autogenerar, intentaría
``CREATE TYPE`` dos veces y la migración fallaría al aplicar.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "1d93d38841b2"
down_revision: str | None = "af45d3a4fbc3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ESTADO_INVENTARIO_VALUES = ("OPERATIVO", "AVERIADO", "PERDIDO", "EN_USO")
ESTADO_INVENTARIO_TYPE_NAME = "estado_inventario"


def upgrade() -> None:
    # Crear el enum compartido `estado_inventario` una sola vez antes de
    # crear las tablas que lo referencian.
    estado_enum = postgresql.ENUM(
        *ESTADO_INVENTARIO_VALUES,
        name=ESTADO_INVENTARIO_TYPE_NAME,
        create_type=False,
    )
    estado_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "materiales",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("nombre", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("descripcion", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("codigo", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("numero_serie", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column(
            "tipo",
            sa.Enum(
                "PERSONAL",
                "PRESTABLE",
                "SERVICIO",
                name="tipo_material",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("categoria", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
        sa.Column("estado", estado_enum, nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("ubicacion_base", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("fecha_adquisicion", sa.Date(), nullable=True),
        sa.Column("fecha_proxima_revision", sa.Date(), nullable=True),
        sa.Column("foto_url", sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
        sa.Column("observaciones_incidencia", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
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
        sa.UniqueConstraint("codigo"),
    )

    op.create_table(
        "vehiculos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("codigo_interno", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("matricula", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column(
            "tipo",
            sa.Enum(
                "FURGONETA",
                "PICK_UP",
                "AMBULANCIA",
                "REMOLQUE",
                name="tipo_vehiculo",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("marca_modelo", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("fecha_itv", sa.Date(), nullable=True),
        sa.Column("foto_url", sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
        sa.Column("observaciones", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("estado", estado_enum, nullable=False),
        sa.Column("ubicacion_base", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("observaciones_incidencia", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
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
        sa.UniqueConstraint("codigo_interno"),
    )

    op.create_table(
        "asignaciones_material",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("material_id", sa.Uuid(), nullable=False),
        sa.Column("voluntario_id", sa.Uuid(), nullable=True),
        sa.Column("servicio_id", sa.Uuid(), nullable=True),
        sa.Column(
            "tipo",
            sa.Enum(
                "PERSONAL",
                "PRESTAMO",
                "SERVICIO",
                name="tipo_asignacion_material",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("fecha_asignacion", sa.DateTime(), nullable=False),
        sa.Column("fecha_devolucion", sa.DateTime(), nullable=True),
        sa.Column(
            "observaciones_devolucion",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
        ),
        sa.CheckConstraint(
            "(voluntario_id IS NOT NULL) <> (servicio_id IS NOT NULL)",
            name="ck_asignacion_material_target",
        ),
        sa.ForeignKeyConstraint(["material_id"], ["materiales.id"]),
        sa.ForeignKeyConstraint(["servicio_id"], ["servicios.id"]),
        sa.ForeignKeyConstraint(["voluntario_id"], ["voluntarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_asignaciones_material_material_id"),
        "asignaciones_material",
        ["material_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_asignaciones_material_servicio_id"),
        "asignaciones_material",
        ["servicio_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_asignaciones_material_voluntario_id"),
        "asignaciones_material",
        ["voluntario_id"],
        unique=False,
    )

    op.create_table(
        "asignaciones_vehiculo",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("vehiculo_id", sa.Uuid(), nullable=False),
        sa.Column("servicio_id", sa.Uuid(), nullable=False),
        sa.Column("fecha_asignacion", sa.DateTime(), nullable=False),
        sa.Column("fecha_devolucion", sa.DateTime(), nullable=True),
        sa.Column("observaciones", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(["servicio_id"], ["servicios.id"]),
        sa.ForeignKeyConstraint(["vehiculo_id"], ["vehiculos.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_asignaciones_vehiculo_servicio_id"),
        "asignaciones_vehiculo",
        ["servicio_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_asignaciones_vehiculo_vehiculo_id"),
        "asignaciones_vehiculo",
        ["vehiculo_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_asignaciones_vehiculo_vehiculo_id"),
        table_name="asignaciones_vehiculo",
    )
    op.drop_index(
        op.f("ix_asignaciones_vehiculo_servicio_id"),
        table_name="asignaciones_vehiculo",
    )
    op.drop_table("asignaciones_vehiculo")

    op.drop_index(
        op.f("ix_asignaciones_material_voluntario_id"),
        table_name="asignaciones_material",
    )
    op.drop_index(
        op.f("ix_asignaciones_material_servicio_id"),
        table_name="asignaciones_material",
    )
    op.drop_index(
        op.f("ix_asignaciones_material_material_id"),
        table_name="asignaciones_material",
    )
    op.drop_table("asignaciones_material")
    op.drop_table("vehiculos")
    op.drop_table("materiales")

    # Drop explícito de los tipos PostgreSQL para mantener la BD limpia
    # tras un downgrade completo.
    sa.Enum(name="tipo_asignacion_material").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="tipo_vehiculo").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="tipo_material").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name=ESTADO_INVENTARIO_TYPE_NAME).drop(
        op.get_bind(), checkfirst=True
    )
