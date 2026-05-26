"""Acreditación concreta de un voluntario.

Patrón ADR-025: instancia de un tipo del catálogo `tipos_acreditacion`
con campos comunes (fechas, número, entidad emisora) + campos específicos
del tipo en JSONB (`datos_especificos`).
"""

import uuid
from datetime import date
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import pk_uuid
from app.models.tipo_acreditacion import (
    CategoriaAcreditacion,
    categoria_acreditacion_enum,
)

if TYPE_CHECKING:
    from app.models.tipo_acreditacion import TipoAcreditacion
    from app.models.voluntario import Voluntario


class Acreditacion(SQLModel, table=True):
    """Carnet, certificación, curso o acreditación obtenida por un voluntario.

    El campo `categoria` se almacena en la instancia (no solo en el tipo)
    para permitir filtros eficientes por familia sin JOIN al catálogo y para
    soportar reclasificación operativa puntual de una instancia.

    Constraint `uq_acreditacion_voluntario_tipo_numero` impide que un mismo
    voluntario registre dos veces el mismo tipo con el mismo número
    (p.ej. dos veces el carnet B con número 12345678). Con `numero=NULL`
    PostgreSQL permite múltiples filas (NULL no se considera duplicado),
    así que cursos internos sin número conviven sin problema.
    """

    __tablename__ = "acreditaciones"

    __table_args__ = (
        UniqueConstraint(
            "voluntario_id",
            "tipo_id",
            "numero",
            name="uq_acreditacion_voluntario_tipo_numero",
        ),
    )

    id: uuid.UUID = pk_uuid()
    voluntario_id: uuid.UUID = Field(foreign_key="voluntarios.id", index=True)
    tipo_id: uuid.UUID = Field(foreign_key="tipos_acreditacion.id", index=True)

    categoria: CategoriaAcreditacion = Field(
        sa_column=Column(categoria_acreditacion_enum, nullable=False, index=True),
    )

    fecha_obtencion: date
    fecha_caducidad: date | None = None
    numero: str | None = Field(default=None, max_length=100)
    entidad_emisora: str | None = Field(default=None, max_length=255)
    # Campos específicos del tipo (validables contra `TipoAcreditacion.campos_schema`).
    datos_especificos: dict | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    documento_url: str | None = Field(default=None, max_length=500)

    voluntario: Optional["Voluntario"] = Relationship(back_populates="acreditaciones")
    tipo: Optional["TipoAcreditacion"] = Relationship(back_populates="acreditaciones")

    def __repr__(self) -> str:
        return (
            f"<Acreditacion voluntario={self.voluntario_id} "
            f"tipo={self.tipo_id} categoria={self.categoria.value}>"
        )
