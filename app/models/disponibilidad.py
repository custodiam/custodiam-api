"""Modelo de Disponibilidad de voluntario."""

import uuid
from datetime import date
from typing import TYPE_CHECKING, Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import pk_uuid

if TYPE_CHECKING:
    from app.models.voluntario import Voluntario


class Disponibilidad(SQLModel, table=True):
    """Día en que un voluntario está disponible o no."""

    __tablename__ = "disponibilidades"

    # Restricción: un voluntario solo tiene una entrada por día
    __table_args__ = (
        UniqueConstraint(
            "voluntario_id", "fecha", name="uq_disponibilidad_voluntario_fecha"
        ),
    )

    id: uuid.UUID = pk_uuid()
    voluntario_id: uuid.UUID = Field(foreign_key="voluntarios.id", index=True)
    fecha: date
    disponible: bool = Field(default=True)

    # Relaciones
    voluntario: Optional["Voluntario"] = Relationship(back_populates="disponibilidades")

    def __repr__(self) -> str:
        marca = "✓" if self.disponible else "✗"
        return f"<Disponibilidad {self.voluntario_id} {self.fecha} {marca}>"
