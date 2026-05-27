"""add dispositivos and notificaciones tables (E06)

Revision ID: b2c3d4e5f6a7
Revises: f76feacaf399
Create Date: 2026-05-27 18:00:00.000000

Crea las tablas del módulo de Notificaciones (Epic E06):

- ``dispositivos``: tokens FCM por voluntario y plataforma (android,
  ios, web), con flag ``activo`` para soft delete.
- ``notificaciones``: audit log de cada notificación emitida (referencia
  opcional a ``servicios.id``).

Los tipos PostgreSQL ``plataforma_dispositivo``, ``tipo_notificacion`` y
``prioridad_notificacion`` se crean implícitamente por
``sa.Enum(..., create_constraint=True)`` al crear las tablas, siguiendo
el patrón ya usado en la migración de servicios (``344062bfa502``).
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "f76feacaf399"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dispositivos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("voluntario_id", sa.Uuid(), nullable=False),
        sa.Column(
            "fcm_token",
            sqlmodel.sql.sqltypes.AutoString(length=512),
            nullable=False,
        ),
        sa.Column(
            "plataforma",
            sa.Enum(
                "ANDROID",
                "IOS",
                "WEB",
                name="plataforma_dispositivo",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "ultima_actualizacion",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["voluntario_id"], ["voluntarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fcm_token"),
    )
    op.create_index(
        op.f("ix_dispositivos_voluntario_id"),
        "dispositivos",
        ["voluntario_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dispositivos_fcm_token"),
        "dispositivos",
        ["fcm_token"],
        unique=True,
    )

    op.create_table(
        "notificaciones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("servicio_id", sa.Uuid(), nullable=True),
        sa.Column(
            "titulo",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column(
            "cuerpo",
            sqlmodel.sql.sqltypes.AutoString(length=2000),
            nullable=False,
        ),
        sa.Column(
            "tipo",
            sa.Enum(
                "EMERGENCIA",
                "SERVICIO",
                "RECORDATORIO",
                "SISTEMA",
                name="tipo_notificacion",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "prioridad",
            sa.Enum(
                "CRITICA",
                "ALTA",
                "NORMAL",
                "BAJA",
                name="prioridad_notificacion",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "enviada_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("enviadas_count", sa.Integer(), nullable=False),
        sa.Column("entregadas_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["servicio_id"], ["servicios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_notificaciones_servicio_id"),
        "notificaciones",
        ["servicio_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_notificaciones_servicio_id"), table_name="notificaciones"
    )
    op.drop_table("notificaciones")

    op.drop_index(
        op.f("ix_dispositivos_fcm_token"), table_name="dispositivos"
    )
    op.drop_index(
        op.f("ix_dispositivos_voluntario_id"), table_name="dispositivos"
    )
    op.drop_table("dispositivos")

    # `sa.Enum(..., create_constraint=True)` no genera DROP TYPE automático
    # en downgrade; lo hacemos explícitamente para mantener la BD limpia.
    sa.Enum(name="prioridad_notificacion").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="tipo_notificacion").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="plataforma_dispositivo").drop(op.get_bind(), checkfirst=True)
