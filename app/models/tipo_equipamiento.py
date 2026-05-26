"""Catálogo extensible de tipos de equipamiento con talla.

Patrón ADR-025: catálogo + tabla de instancias.
Las tallas concretas viven en `app.models.talla_voluntario.TallaVoluntario`.
"""

import uuid
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import pk_uuid

if TYPE_CHECKING:
    from app.models.talla_voluntario import TallaVoluntario


class TipoEquipamiento(SQLModel, table=True):
    """Tipo predefinido de equipamiento con talla (camisa, botas, casco, etc.).

    Pre-poblado vía Alembic data migration con los items canónicos
    del proyecto. Añadir un tipo nuevo es una fila nueva.

    El campo `sistema_tallas` describe la convención (p.ej. "XS-XXXL",
    "36-50", "EU") para que la UI pueda validar / sugerir valores
    coherentes; no se enforza en BD para permitir flexibilidad operativa.
    """

    __tablename__ = "tipos_equipamiento"

    id: uuid.UUID = pk_uuid()
    codigo: str = Field(max_length=50, unique=True, index=True)
    nombre: str = Field(max_length=255)
    sistema_tallas: str | None = Field(default=None, max_length=50)
    activo: bool = Field(default=True, nullable=False)

    tallas: list["TallaVoluntario"] = Relationship(back_populates="tipo")

    def __repr__(self) -> str:
        return f"<TipoEquipamiento {self.codigo}>"
