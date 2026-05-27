"""add servicios and inscripciones_servicio tables (EN-03-01)

Revision ID: 344062bfa502
Revises: 08460f65687b
Create Date: 2026-05-27 10:39:39.173675

Crea las tablas del módulo de Servicios (Epic E03):

- ``servicios``: cabecera del servicio (preventivo, emergencia, formación
  u otro). Contiene la máquina de estados (borrador → publicado → activo
  → cerrado) y los datos del CU-01.
- ``inscripciones_servicio``: relación N:M entre voluntarios y servicios
  con un discriminador ``tipo`` (inscrito / convocado) que distingue
  el CU-04 (voluntario se apunta) del CU-03 (mando convoca).

Los tipos PostgreSQL ``tipo_servicio``, ``estado_servicio`` y
``tipo_inscripcion`` se crean implícitamente por ``sa.Enum(...,
create_constraint=True)`` al crear las tablas que los referencian.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "344062bfa502"
down_revision: str | None = "08460f65687b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "servicios",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "titulo",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column(
            "descripcion", sqlmodel.sql.sqltypes.AutoString(), nullable=True
        ),
        sa.Column(
            "tipo",
            sa.Enum(
                "PREVENTIVO",
                "EMERGENCIA",
                "FORMACION",
                "OTRO",
                name="tipo_servicio",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "estado",
            sa.Enum(
                "BORRADOR",
                "PUBLICADO",
                "ACTIVO",
                "CERRADO",
                name="estado_servicio",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("fecha_inicio", sa.DateTime(), nullable=False),
        sa.Column("fecha_fin", sa.DateTime(), nullable=True),
        sa.Column(
            "ubicacion",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column("numero_voluntarios", sa.Integer(), nullable=True),
        sa.Column(
            "notas_material",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
        ),
        sa.Column(
            "notas_vehiculos",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
        ),
        sa.Column(
            "observaciones_cierre",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
        ),
        sa.Column(
            "creado_por_keycloak_id",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column("fecha_cierre", sa.DateTime(), nullable=True),
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
    )
    op.create_index(
        op.f("ix_servicios_creado_por_keycloak_id"),
        "servicios",
        ["creado_por_keycloak_id"],
        unique=False,
    )

    op.create_table(
        "inscripciones_servicio",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("servicio_id", sa.Uuid(), nullable=False),
        sa.Column("voluntario_id", sa.Uuid(), nullable=False),
        sa.Column(
            "tipo",
            sa.Enum(
                "INSCRITO",
                "CONVOCADO",
                name="tipo_inscripcion",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("fecha", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["servicio_id"], ["servicios.id"]),
        sa.ForeignKeyConstraint(["voluntario_id"], ["voluntarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "servicio_id",
            "voluntario_id",
            name="uq_inscripcion_servicio_voluntario",
        ),
    )
    op.create_index(
        op.f("ix_inscripciones_servicio_servicio_id"),
        "inscripciones_servicio",
        ["servicio_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inscripciones_servicio_voluntario_id"),
        "inscripciones_servicio",
        ["voluntario_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_inscripciones_servicio_voluntario_id"),
        table_name="inscripciones_servicio",
    )
    op.drop_index(
        op.f("ix_inscripciones_servicio_servicio_id"),
        table_name="inscripciones_servicio",
    )
    op.drop_table("inscripciones_servicio")
    op.drop_index(
        op.f("ix_servicios_creado_por_keycloak_id"), table_name="servicios"
    )
    op.drop_table("servicios")
    # `sa.Enum(..., create_constraint=True)` no genera DROP TYPE automático
    # en downgrade; lo hacemos explícitamente para mantener la BD limpia.
    sa.Enum(name="tipo_inscripcion").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="estado_servicio").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="tipo_servicio").drop(op.get_bind(), checkfirst=True)
