"""Contacto de emergencia de un voluntario."""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import pk_uuid

if TYPE_CHECKING:
    from app.models.voluntario import Voluntario


class ContactoEmergencia(SQLModel, table=True):
    """Persona a contactar en caso de emergencia con el voluntario.

    Un voluntario puede declarar varios contactos ordenados por preferencia
    de llamada (`orden_preferencia=1` es el primer contacto a llamar).
    `parentesco` es texto libre porque no hay catálogo razonable que cubra
    todas las relaciones humanas relevantes ("madre", "cónyuge",
    "compañero de piso", "amigo cercano"...).
    """

    __tablename__ = "contactos_emergencia"

    id: uuid.UUID = pk_uuid()
    voluntario_id: uuid.UUID = Field(foreign_key="voluntarios.id", index=True)
    nombre: str = Field(max_length=255)
    telefono: str = Field(max_length=20)
    parentesco: str | None = Field(default=None, max_length=100)
    orden_preferencia: int = Field(default=1, nullable=False)

    voluntario: Optional["Voluntario"] = Relationship(back_populates="contactos_emergencia")

    def __repr__(self) -> str:
        return (
            f"<ContactoEmergencia {self.nombre} ({self.telefono}) "
            f"voluntario={self.voluntario_id}>"
        )
