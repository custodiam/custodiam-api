"""extend voluntario with catalogos extensibles (EN-02-01)

Revision ID: 08460f65687b
Revises: 0f59798cd66b
Create Date: 2026-05-26 14:42:37.127422

Applies ADR-025 ("Modelo de datos extensible para acreditaciones, tallas
y catálogos del módulo voluntarios"):

Fase 1 — Extend `voluntarios` con 4 columnas nuevas + promote `telefono`
        a NOT NULL (asume tabla vacía sin datos productivos).

Fase 2 — Create 5 new tables:
    - tipos_acreditacion         (catálogo)
    - acreditaciones             (instancias, FK a voluntarios + tipos_acreditacion)
    - tipos_equipamiento         (catálogo)
    - tallas_voluntario          (1:N, UNIQUE voluntario+tipo)
    - contactos_emergencia       (1:N puro, sin catálogo)

Fase 3 — Seed catálogos (data migration):
    - tipos_acreditacion: 8 tipos iniciales (CARNET_CONDUCIR, ESS_SANITARIO,
      ADR_MERCANCIAS_PELIGROSAS, MANIPULADOR_ALIMENTOS, CURSO_DEA,
      CURSO_PROTECCION_CIVIL, JORNADA_RESCATE_VEHICULOS, OTRO).
    - tipos_equipamiento: 8 tipos iniciales (CAMISA, POLO, CHAQUETA,
      PANTALON, BOTAS, CASCO, GUANTES, CHALECO).

Fase 4 — Drop tabla `formaciones` (creada en revision 0f59798cd66b,
        vacía sin datos productivos; las certificaciones de formación
        pasan a `acreditaciones` con categoria='formacion_interna').
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "08460f65687b"
down_revision: str | None = "0f59798cd66b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Reutilizamos el mismo nombre de tipo PostgreSQL en upgrade/downgrade.
CATEGORIA_ACREDITACION_VALUES = ("licencia_oficial", "formacion_interna", "otro")
CATEGORIA_ACREDITACION_TYPE_NAME = "categoria_acreditacion"


def upgrade() -> None:
    # ---------------------------------------------------------------- #
    # Fase 1 — Extender `voluntarios` con 4 columnas + telefono NOT NULL
    # ---------------------------------------------------------------- #

    # Añadimos las columnas obligatorias como nullable primero y aplicamos
    # NOT NULL después con un valor por defecto seguro para filas existentes.
    # En este proyecto la tabla está vacía al momento de aplicar, así que
    # `server_default` se elimina inmediatamente para que SQLModel no lo
    # interprete como `default=...` en futuras inserciones.
    op.add_column(
        "voluntarios",
        sa.Column("municipio", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    )
    op.add_column(
        "voluntarios",
        sa.Column("fecha_nacimiento", sa.Date(), nullable=True),
    )
    op.add_column(
        "voluntarios",
        sa.Column(
            "direccion",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
    )
    op.add_column(
        "voluntarios",
        sa.Column(
            "conductor_habilitado",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Telefono pasa a NOT NULL — asumimos tabla vacía (sin datos productivos).
    op.alter_column(
        "voluntarios",
        "telefono",
        existing_type=sqlmodel.sql.sqltypes.AutoString(length=20),
        nullable=False,
    )
    # Y promovemos municipio + fecha_nacimiento a NOT NULL ahora que
    # cualquier fila existente tendría que haber sido completada manualmente
    # (no aplicable aquí: tabla vacía).
    op.alter_column(
        "voluntarios",
        "municipio",
        existing_type=sqlmodel.sql.sqltypes.AutoString(length=100),
        nullable=False,
    )
    op.alter_column(
        "voluntarios",
        "fecha_nacimiento",
        existing_type=sa.Date(),
        nullable=False,
    )

    # Quitamos el server_default de conductor_habilitado: el default real lo
    # gestiona el modelo SQLModel (Field(default=False)). Mantener el
    # server_default introduciría inconsistencia entre el modelo y la BD.
    op.alter_column(
        "voluntarios",
        "conductor_habilitado",
        existing_type=sa.Boolean(),
        server_default=None,
    )

    # ---------------------------------------------------------------- #
    # Fase 2 — Crear las 5 tablas nuevas
    # ---------------------------------------------------------------- #

    # Tipo PostgreSQL `categoria_acreditacion` (enum). Se crea explícitamente
    # antes de las tablas que lo referencian para que SQLAlchemy no intente
    # crearlo dos veces (una por cada columna que lo usa).
    categoria_enum = postgresql.ENUM(
        *CATEGORIA_ACREDITACION_VALUES,
        name=CATEGORIA_ACREDITACION_TYPE_NAME,
        create_type=False,
    )
    categoria_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "tipos_acreditacion",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "codigo",
            sqlmodel.sql.sqltypes.AutoString(length=50),
            nullable=False,
        ),
        sa.Column(
            "nombre",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column("descripcion", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("categoria", categoria_enum, nullable=False),
        sa.Column(
            "campos_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("codigo"),
    )
    op.create_index(
        op.f("ix_tipos_acreditacion_codigo"),
        "tipos_acreditacion",
        ["codigo"],
        unique=True,
    )

    op.create_table(
        "acreditaciones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("voluntario_id", sa.Uuid(), nullable=False),
        sa.Column("tipo_id", sa.Uuid(), nullable=False),
        sa.Column("categoria", categoria_enum, nullable=False),
        sa.Column("fecha_obtencion", sa.Date(), nullable=False),
        sa.Column("fecha_caducidad", sa.Date(), nullable=True),
        sa.Column(
            "numero",
            sqlmodel.sql.sqltypes.AutoString(length=100),
            nullable=True,
        ),
        sa.Column(
            "entidad_emisora",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column(
            "datos_especificos",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "documento_url",
            sqlmodel.sql.sqltypes.AutoString(length=500),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["tipo_id"], ["tipos_acreditacion.id"]),
        sa.ForeignKeyConstraint(["voluntario_id"], ["voluntarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "voluntario_id",
            "tipo_id",
            "numero",
            name="uq_acreditacion_voluntario_tipo_numero",
        ),
    )
    op.create_index(
        op.f("ix_acreditaciones_voluntario_id"),
        "acreditaciones",
        ["voluntario_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_acreditaciones_tipo_id"),
        "acreditaciones",
        ["tipo_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_acreditaciones_categoria"),
        "acreditaciones",
        ["categoria"],
        unique=False,
    )

    op.create_table(
        "tipos_equipamiento",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "codigo",
            sqlmodel.sql.sqltypes.AutoString(length=50),
            nullable=False,
        ),
        sa.Column(
            "nombre",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column(
            "sistema_tallas",
            sqlmodel.sql.sqltypes.AutoString(length=50),
            nullable=True,
        ),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("codigo"),
    )
    op.create_index(
        op.f("ix_tipos_equipamiento_codigo"),
        "tipos_equipamiento",
        ["codigo"],
        unique=True,
    )

    op.create_table(
        "tallas_voluntario",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("voluntario_id", sa.Uuid(), nullable=False),
        sa.Column("tipo_id", sa.Uuid(), nullable=False),
        sa.Column(
            "valor",
            sqlmodel.sql.sqltypes.AutoString(length=20),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tipo_id"], ["tipos_equipamiento.id"]),
        sa.ForeignKeyConstraint(["voluntario_id"], ["voluntarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "voluntario_id",
            "tipo_id",
            name="uq_talla_voluntario_tipo",
        ),
    )
    op.create_index(
        op.f("ix_tallas_voluntario_voluntario_id"),
        "tallas_voluntario",
        ["voluntario_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tallas_voluntario_tipo_id"),
        "tallas_voluntario",
        ["tipo_id"],
        unique=False,
    )

    op.create_table(
        "contactos_emergencia",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("voluntario_id", sa.Uuid(), nullable=False),
        sa.Column(
            "nombre",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column(
            "telefono",
            sqlmodel.sql.sqltypes.AutoString(length=20),
            nullable=False,
        ),
        sa.Column(
            "parentesco",
            sqlmodel.sql.sqltypes.AutoString(length=100),
            nullable=True,
        ),
        sa.Column("orden_preferencia", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["voluntario_id"], ["voluntarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_contactos_emergencia_voluntario_id"),
        "contactos_emergencia",
        ["voluntario_id"],
        unique=False,
    )

    # ---------------------------------------------------------------- #
    # Fase 3 — Seed catálogos (data migration)
    # ---------------------------------------------------------------- #
    # Los UUIDs se generan en Python con uuid.uuid4(). Evitamos
    # depender de extensiones PostgreSQL (pgcrypto / uuid-ossp) en la
    # data migration: con bulk_insert(), SQLAlchemy no sustituye
    # objetos sa.text() dentro de los parámetros (los pasa como
    # TextClause y el driver psycopg falla con "cannot adapt type
    # 'TextClause'"). uuid.uuid4() devuelve un UUID nativo Python que
    # psycopg sabe adaptar a la columna sa.Uuid().

    tipos_acreditacion_table = sa.table(
        "tipos_acreditacion",
        sa.column("id", sa.Uuid()),
        sa.column("codigo", sqlmodel.sql.sqltypes.AutoString()),
        sa.column("nombre", sqlmodel.sql.sqltypes.AutoString()),
        sa.column("descripcion", sqlmodel.sql.sqltypes.AutoString()),
        sa.column("categoria", categoria_enum),
        sa.column("campos_schema", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("activo", sa.Boolean()),
    )
    op.bulk_insert(
        tipos_acreditacion_table,
        [
            {
                "id": uuid.uuid4(),
                "codigo": "CARNET_CONDUCIR",
                "nombre": "Carnet de conducir",
                "descripcion": "Permiso de conducción oficial emitido por la DGT.",
                "categoria": "licencia_oficial",
                "campos_schema": {
                    "tipo": "B | B+E | C | C+E | D",
                    "incluye_remolque": "bool",
                },
                "activo": True,
            },
            {
                "id": uuid.uuid4(),
                "codigo": "ESS_SANITARIO",
                "nombre": "ESS sanitario",
                "descripcion": (
                    "Titulación sanitaria reconocida (ESS, ATS, "
                    "enfermería). Habilita asistencia en servicios."
                ),
                "categoria": "licencia_oficial",
                "campos_schema": {"nivel": "ESS | ATS | enfermería"},
                "activo": True,
            },
            {
                "id": uuid.uuid4(),
                "codigo": "ADR_MERCANCIAS_PELIGROSAS",
                "nombre": "ADR Mercancías Peligrosas",
                "descripcion": "Acreditación ADR para transporte de mercancías peligrosas.",
                "categoria": "licencia_oficial",
                "campos_schema": {
                    "clases": ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX"]
                },
                "activo": True,
            },
            {
                "id": uuid.uuid4(),
                "codigo": "MANIPULADOR_ALIMENTOS",
                "nombre": "Manipulador de alimentos",
                "descripcion": "Certificado oficial de manipulador de alimentos.",
                "categoria": "licencia_oficial",
                "campos_schema": {},
                "activo": True,
            },
            {
                "id": uuid.uuid4(),
                "codigo": "CURSO_DEA",
                "nombre": "Curso de uso de DEA",
                "descripcion": (
                    "Curso interno de uso del Desfibrilador "
                    "Externo Automático (DEA)."
                ),
                "categoria": "formacion_interna",
                "campos_schema": {},
                "activo": True,
            },
            {
                "id": uuid.uuid4(),
                "codigo": "CURSO_PROTECCION_CIVIL",
                "nombre": "Curso de Protección Civil",
                "descripcion": "Curso interno genérico de Protección Civil.",
                "categoria": "formacion_interna",
                "campos_schema": {
                    "horas": "int",
                    "nivel": "básico | intermedio | avanzado",
                },
                "activo": True,
            },
            {
                "id": uuid.uuid4(),
                "codigo": "JORNADA_RESCATE_VEHICULOS",
                "nombre": "Jornada de rescate en vehículos",
                "descripcion": "Jornada formativa interna sobre rescate vehicular.",
                "categoria": "formacion_interna",
                "campos_schema": {},
                "activo": True,
            },
            {
                "id": uuid.uuid4(),
                "codigo": "OTRO",
                "nombre": "Otra acreditación",
                "descripcion": "Tipo genérico para acreditaciones no catalogadas todavía.",
                "categoria": "otro",
                "campos_schema": None,
                "activo": True,
            },
        ],
    )

    tipos_equipamiento_table = sa.table(
        "tipos_equipamiento",
        sa.column("id", sa.Uuid()),
        sa.column("codigo", sqlmodel.sql.sqltypes.AutoString()),
        sa.column("nombre", sqlmodel.sql.sqltypes.AutoString()),
        sa.column("sistema_tallas", sqlmodel.sql.sqltypes.AutoString()),
        sa.column("activo", sa.Boolean()),
    )
    op.bulk_insert(
        tipos_equipamiento_table,
        [
            {
                "id": uuid.uuid4(),
                "codigo": "CAMISA",
                "nombre": "Camisa",
                "sistema_tallas": "XS-XXXL",
                "activo": True,
            },
            {
                "id": uuid.uuid4(),
                "codigo": "POLO",
                "nombre": "Polo",
                "sistema_tallas": "XS-XXXL",
                "activo": True,
            },
            {
                "id": uuid.uuid4(),
                "codigo": "CHAQUETA",
                "nombre": "Chaqueta",
                "sistema_tallas": "XS-XXXL",
                "activo": True,
            },
            {
                "id": uuid.uuid4(),
                "codigo": "PANTALON",
                "nombre": "Pantalón",
                "sistema_tallas": "36-50",
                "activo": True,
            },
            {
                "id": uuid.uuid4(),
                "codigo": "BOTAS",
                "nombre": "Botas",
                "sistema_tallas": "36-50",
                "activo": True,
            },
            {
                "id": uuid.uuid4(),
                "codigo": "CASCO",
                "nombre": "Casco",
                "sistema_tallas": "S-XL",
                "activo": True,
            },
            {
                "id": uuid.uuid4(),
                "codigo": "GUANTES",
                "nombre": "Guantes",
                "sistema_tallas": "S-XL",
                "activo": True,
            },
            {
                "id": uuid.uuid4(),
                "codigo": "CHALECO",
                "nombre": "Chaleco reflectante",
                "sistema_tallas": "XS-XXXL",
                "activo": True,
            },
        ],
    )

    # ---------------------------------------------------------------- #
    # Fase 4 — Drop tabla `formaciones`
    # ---------------------------------------------------------------- #
    # Las certificaciones de formación pasan a `acreditaciones` con
    # categoria='formacion_interna'. La tabla `formaciones` está vacía
    # al momento de aplicar esta migración (sin datos productivos).
    op.drop_index("ix_formaciones_voluntario_id", table_name="formaciones")
    op.drop_table("formaciones")


def downgrade() -> None:
    # Recrear `formaciones` tal y como existía en la revision 0f59798cd66b.
    op.create_table(
        "formaciones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("voluntario_id", sa.Uuid(), nullable=False),
        sa.Column(
            "titulo",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column("fecha_obtencion", sa.Date(), nullable=False),
        sa.Column("fecha_caducidad", sa.Date(), nullable=True),
        sa.Column("certificado_url", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(["voluntario_id"], ["voluntarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_formaciones_voluntario_id"),
        "formaciones",
        ["voluntario_id"],
        unique=False,
    )

    # Drop nuevas tablas en orden inverso a su creación (respetando FKs).
    op.drop_index(
        op.f("ix_contactos_emergencia_voluntario_id"), table_name="contactos_emergencia"
    )
    op.drop_table("contactos_emergencia")

    op.drop_index(op.f("ix_tallas_voluntario_tipo_id"), table_name="tallas_voluntario")
    op.drop_index(op.f("ix_tallas_voluntario_voluntario_id"), table_name="tallas_voluntario")
    op.drop_table("tallas_voluntario")

    op.drop_index(op.f("ix_tipos_equipamiento_codigo"), table_name="tipos_equipamiento")
    op.drop_table("tipos_equipamiento")

    op.drop_index(op.f("ix_acreditaciones_categoria"), table_name="acreditaciones")
    op.drop_index(op.f("ix_acreditaciones_tipo_id"), table_name="acreditaciones")
    op.drop_index(op.f("ix_acreditaciones_voluntario_id"), table_name="acreditaciones")
    op.drop_table("acreditaciones")

    op.drop_index(op.f("ix_tipos_acreditacion_codigo"), table_name="tipos_acreditacion")
    op.drop_table("tipos_acreditacion")

    # Drop del tipo enum `categoria_acreditacion`.
    categoria_enum = postgresql.ENUM(
        *CATEGORIA_ACREDITACION_VALUES,
        name=CATEGORIA_ACREDITACION_TYPE_NAME,
    )
    categoria_enum.drop(op.get_bind(), checkfirst=True)

    # Revertir cambios en `voluntarios`.
    op.drop_column("voluntarios", "conductor_habilitado")
    op.drop_column("voluntarios", "direccion")
    op.drop_column("voluntarios", "fecha_nacimiento")
    op.drop_column("voluntarios", "municipio")
    op.alter_column(
        "voluntarios",
        "telefono",
        existing_type=sqlmodel.sql.sqltypes.AutoString(length=20),
        nullable=True,
    )
