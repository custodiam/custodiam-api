"""Modelo de Rol jerárquico."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import pk_uuid

if TYPE_CHECKING:
    from app.models.voluntario_rol import VoluntarioRol


class Rol(SQLModel, table=True):
    """Rol dentro de la jerarquía de la agrupación."""

    __tablename__ = "roles"

    id: uuid.UUID = pk_uuid()
    nombre: str = Field(max_length=100, unique=True)
    nivel: int = Field(description="Nivel jerárquico (1-10)")
    descripcion: str | None = Field(default=None)

    # Permisos — usa sa_column para JSONB de PostgreSQL
    permisos: dict | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )

    # Relaciones
    voluntarios: list["VoluntarioRol"] = Relationship(back_populates="rol")

    def __repr__(self) -> str:
        return f"<Rol {self.nombre} (nivel {self.nivel})>"
