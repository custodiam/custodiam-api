"""Catálogo extensible de tipos de acreditación.

Patrón ADR-025: catálogo + tabla de instancias + JSONB para campos específicos.
Las instancias concretas viven en `app.models.acreditacion.Acreditacion`.
"""

import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Column
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import pk_uuid

if TYPE_CHECKING:
    from app.models.acreditacion import Acreditacion


class CategoriaAcreditacion(enum.StrEnum):
    """Familia conceptual de una acreditación.

    Se usa como discriminador tanto en `TipoAcreditacion.categoria`
    (familia sugerida por defecto al crear instancias del tipo) como
    en `Acreditacion.categoria` (familia real de la instancia, que
    puede divergir del tipo en casos excepcionales de reclasificación
    operativa).
    """

    LICENCIA_OFICIAL = "licencia_oficial"
    FORMACION_INTERNA = "formacion_interna"
    OTRO = "otro"


# Definición única del PostgreSQL enum `categoria_acreditacion`,
# compartida por `TipoAcreditacion.categoria` y `Acreditacion.categoria`
# para que SQLAlchemy emita un solo `CREATE TYPE` (ADR-025).
categoria_acreditacion_enum = SAEnum(
    CategoriaAcreditacion,
    name="categoria_acreditacion",
    create_constraint=True,
)


class TipoAcreditacion(SQLModel, table=True):
    """Tipo predefinido de acreditación (carnet, certificación, curso, etc.).

    Pre-poblado vía Alembic data migration con los tipos canónicos del
    proyecto. Añadir un tipo nuevo es una fila nueva (no schema migration).
    """

    __tablename__ = "tipos_acreditacion"

    id: uuid.UUID = pk_uuid()
    codigo: str = Field(max_length=50, unique=True, index=True)
    nombre: str = Field(max_length=255)
    descripcion: str | None = None
    categoria: CategoriaAcreditacion = Field(
        sa_column=Column(categoria_acreditacion_enum, nullable=False),
    )
    # JSON schema que documenta la forma esperada de
    # `Acreditacion.datos_especificos` para este tipo. Validación opcional
    # en la capa API (FastAPI + Pydantic + jsonschema).
    campos_schema: dict | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    activo: bool = Field(default=True, nullable=False)

    acreditaciones: list["Acreditacion"] = Relationship(back_populates="tipo")

    def __repr__(self) -> str:
        return f"<TipoAcreditacion {self.codigo} ({self.categoria.value})>"
