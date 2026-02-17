"""Modelo de asignación Voluntario-Rol (tabla intermedia)."""

import uuid
from datetime import date
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import pk_uuid

if TYPE_CHECKING:
    from app.models.rol import Rol
    from app.models.voluntario import Voluntario


class VoluntarioRol(SQLModel, table=True):
    """Asignación de un rol a un voluntario con periodo de vigencia."""

    __tablename__ = "voluntario_roles"

    id: uuid.UUID = pk_uuid()
    voluntario_id: uuid.UUID = Field(foreign_key="voluntarios.id", index=True)
    rol_id: uuid.UUID = Field(foreign_key="roles.id", index=True)
    fecha_desde: date
    fecha_hasta: date | None = None

    # Relaciones — Optional["X"] en vez de "X | None" para que
    # SQLAlchemy resuelva el forward reference correctamente
    voluntario: Optional["Voluntario"] = Relationship(back_populates="roles")
    rol: Optional["Rol"] = Relationship(back_populates="voluntarios")

    def __repr__(self) -> str:
        return f"<VoluntarioRol voluntario={self.voluntario_id} rol={self.rol_id}>"
