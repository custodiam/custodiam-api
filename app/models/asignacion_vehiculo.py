"""Modelo de AsignacionVehiculo (EN-05-03 / US-05-07)."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import pk_uuid

if TYPE_CHECKING:
    from app.models.servicio import Servicio
    from app.models.vehiculo import Vehiculo


class AsignacionVehiculo(SQLModel, table=True):
    """Asignación de vehículo a un servicio.

    A diferencia de :class:`AsignacionMaterial` aquí no hay un voluntario
    porque los vehículos no se asignan personalmente; siempre van a
    servicio. La asignación está **activa** mientras
    ``fecha_devolucion IS NULL``. Igual que `AsignacionMaterial`, se
    sella al cerrar el servicio (auto-liberación, ver
    `app.services.servicios.cerrar`).
    """

    __tablename__ = "asignaciones_vehiculo"

    id: uuid.UUID = pk_uuid()
    vehiculo_id: uuid.UUID = Field(foreign_key="vehiculos.id", index=True)
    servicio_id: uuid.UUID = Field(foreign_key="servicios.id", index=True)
    fecha_asignacion: datetime
    fecha_devolucion: datetime | None = None
    observaciones: str | None = None

    # Relaciones
    vehiculo: Optional["Vehiculo"] = Relationship(back_populates="asignaciones")
    servicio: Optional["Servicio"] = Relationship()

    @property
    def activa(self) -> bool:
        return self.fecha_devolucion is None

    def __repr__(self) -> str:
        return (
            f"<AsignacionVehiculo vehiculo={self.vehiculo_id} "
            f"servicio={self.servicio_id} activa={self.activa}>"
        )
