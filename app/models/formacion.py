"""Modelo de Formación / Certificado de voluntario."""

import uuid
from datetime import date
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import pk_uuid

if TYPE_CHECKING:
    from app.models.voluntario import Voluntario


class Formacion(SQLModel, table=True):
    """Curso o certificado obtenido por un voluntario."""

    __tablename__ = "formaciones"

    id: uuid.UUID = pk_uuid()
    voluntario_id: uuid.UUID = Field(foreign_key="voluntarios.id", index=True)
    titulo: str = Field(max_length=255)
    fecha_obtencion: date
    fecha_caducidad: date | None = None
    certificado_url: str | None = None

    # Relaciones
    voluntario: Optional["Voluntario"] = Relationship(back_populates="formaciones")

    def __repr__(self) -> str:
        return f"<Formacion {self.titulo} ({self.voluntario_id})>"
