"""Modelo de Vehiculo (Epic E05).

Tabla separada de :class:`Material` por divergencia de campos
(``matricula``, ``fecha_itv``, ``codigo_interno`` no aplican al material;
``cantidad`` no aplica al vehículo que es siempre único) y por corte
distinto del RBAC (``inventario.registrar_vehiculo`` exige jefe_unidad+).

Comparte el enum :class:`EstadoInventario` con `Material` porque las
transiciones operativas son idénticas (OPERATIVO → AVERIADO / PERDIDO /
EN_USO).
"""

import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Column
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import created_at_column, pk_uuid, updated_at_column
from app.models.material import EstadoInventario

if TYPE_CHECKING:
    from app.models.asignacion_vehiculo import AsignacionVehiculo


class TipoVehiculo(enum.StrEnum):
    """Categorías canónicas de vehículo de la agrupación (US-05-02)."""

    FURGONETA = "furgoneta"
    PICK_UP = "pick_up"
    AMBULANCIA = "ambulancia"
    REMOLQUE = "remolque"


class Vehiculo(SQLModel, table=True):
    """Vehículo de la agrupación."""

    __tablename__ = "vehiculos"

    id: uuid.UUID = pk_uuid()

    # Identificación
    codigo_interno: str = Field(max_length=255, unique=True)
    matricula: str = Field(max_length=255)
    tipo: TipoVehiculo = Field(
        sa_column=Column(
            SAEnum(TipoVehiculo, name="tipo_vehiculo", create_constraint=True),
            nullable=False,
        ),
    )

    # Datos opcionales del CU-20 flujo A
    marca_modelo: str | None = Field(default=None, max_length=255)
    fecha_itv: date | None = None
    foto_url: str | None = Field(default=None, max_length=500)
    observaciones: str | None = None

    # Estado
    estado: EstadoInventario = Field(
        default=EstadoInventario.OPERATIVO,
        sa_column=Column(
            SAEnum(
                EstadoInventario,
                name="estado_inventario",
                create_constraint=True,
                # `create_type=False` evita el segundo `CREATE TYPE` de
                # SQLAlchemy: el tipo ya lo crea Material al ser el primero
                # en la metadata.
                create_type=False,
            ),
            nullable=False,
            default=EstadoInventario.OPERATIVO,
        ),
    )
    ubicacion_base: str = Field(max_length=255)
    observaciones_incidencia: str | None = None

    # Timestamps
    created_at: datetime | None = created_at_column()
    updated_at: datetime | None = updated_at_column()

    # Relaciones
    asignaciones: list["AsignacionVehiculo"] = Relationship(
        back_populates="vehiculo"
    )

    def __repr__(self) -> str:
        return (
            f"<Vehiculo {self.codigo_interno!r} "
            f"({self.tipo.value}/{self.estado.value})>"
        )
