"""Modelo de Voluntario."""

import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Column
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import created_at_column, pk_uuid, updated_at_column

if TYPE_CHECKING:
    from app.models.disponibilidad import Disponibilidad
    from app.models.formacion import Formacion
    from app.models.voluntario_rol import VoluntarioRol


class EstadoVoluntario(enum.StrEnum):
    """Estados posibles de un voluntario."""

    ACTIVO = "activo"
    BAJA = "baja"
    SUSPENDIDO = "suspendido"


class Voluntario(SQLModel, table=True):
    """Voluntario de la agrupación de Protección Civil."""

    __tablename__ = "voluntarios"

    # Identificación
    id: uuid.UUID = pk_uuid()
    keycloak_id: str | None = Field(
        default=None, max_length=255, unique=True, index=True
    )

    # Datos personales
    nombre: str = Field(max_length=255)
    dni: str | None = Field(default=None, max_length=20, unique=True)
    email: str | None = Field(default=None, max_length=255, unique=True)
    telefono: str | None = Field(default=None, max_length=20)

    # Fechas
    fecha_alta: date
    fecha_baja: date | None = None

    # Otros
    foto_url: str | None = None

    # Estado — usa sa_column para Enum de PostgreSQL
    estado: EstadoVoluntario = Field(
        default=EstadoVoluntario.ACTIVO,
        sa_column=Column(
            SAEnum(
                EstadoVoluntario,
                name="estado_voluntario",
                create_constraint=True,
            ),
            nullable=False,
            default=EstadoVoluntario.ACTIVO,
        ),
    )

    # Timestamps
    created_at: datetime | None = created_at_column()
    updated_at: datetime | None = updated_at_column()

    # Relaciones
    roles: list["VoluntarioRol"] = Relationship(back_populates="voluntario")
    disponibilidades: list["Disponibilidad"] = Relationship(back_populates="voluntario")
    formaciones: list["Formacion"] = Relationship(back_populates="voluntario")

    def __repr__(self) -> str:
        return f"<Voluntario {self.nombre} ({self.estado.value})>"
