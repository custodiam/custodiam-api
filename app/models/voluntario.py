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
    from app.models.acreditacion import Acreditacion
    from app.models.contacto_emergencia import ContactoEmergencia
    from app.models.disponibilidad import Disponibilidad
    from app.models.talla_voluntario import TallaVoluntario
    from app.models.voluntario_rol import VoluntarioRol


class EstadoVoluntario(enum.StrEnum):
    """Estados posibles de un voluntario."""

    ACTIVO = "activo"
    BAJA = "baja"
    SUSPENDIDO = "suspendido"


class Voluntario(SQLModel, table=True):
    """Voluntario de la agrupación de Protección Civil.

    El modelo se amplía en EN-02-01 (Sprint 4) según ADR-025 con campos
    obligatorios del CU-10 (municipio, fecha_nacimiento), opcionales
    (direccion, conductor_habilitado) y promoción de telefono a NOT NULL.
    Las acreditaciones, tallas de equipamiento y contactos de emergencia
    viven en tablas relacionadas siguiendo el patrón catálogo + instancias.
    """

    __tablename__ = "voluntarios"

    # Identificación
    id: uuid.UUID = pk_uuid()
    keycloak_id: str | None = Field(
        default=None, max_length=255, unique=True, index=True
    )

    # Datos personales obligatorios
    nombre: str = Field(max_length=255)
    telefono: str = Field(max_length=20)
    municipio: str = Field(max_length=100)
    fecha_nacimiento: date

    # Datos personales opcionales
    dni: str | None = Field(default=None, max_length=20, unique=True)
    email: str | None = Field(default=None, max_length=255, unique=True)
    direccion: str | None = Field(default=None, max_length=255)
    foto_url: str | None = None

    # Flag operativo (separado de tener carnet de conducir):
    # un voluntario puede tener carnet B pero la agrupación no le habilita
    # aún para conducir vehículos operativos.
    conductor_habilitado: bool = Field(default=False, nullable=False)

    # Fechas de alta/baja en la agrupación
    fecha_alta: date
    fecha_baja: date | None = None

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
    acreditaciones: list["Acreditacion"] = Relationship(back_populates="voluntario")
    tallas: list["TallaVoluntario"] = Relationship(back_populates="voluntario")
    contactos_emergencia: list["ContactoEmergencia"] = Relationship(
        back_populates="voluntario"
    )

    def __repr__(self) -> str:
        return f"<Voluntario {self.nombre} ({self.estado.value})>"
