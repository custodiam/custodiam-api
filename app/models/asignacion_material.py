"""Modelo de AsignacionMaterial (EN-05-03)."""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, Column
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import pk_uuid

if TYPE_CHECKING:
    from app.models.material import Material
    from app.models.servicio import Servicio
    from app.models.vehiculo import Vehiculo
    from app.models.voluntario import Voluntario


class TipoAsignacion(enum.StrEnum):
    """Discriminador del flujo de asignación (CU-21 / CU-22 / PR3)."""

    # Equipamiento personal fijo asignado al voluntario (US-05-03).
    PERSONAL = "personal"
    # Préstamo temporal a un voluntario, pendiente de devolución (US-05-04).
    PRESTAMO = "prestamo"
    # Material reservado para un servicio concreto (US-05-06).
    SERVICIO = "servicio"
    # Dotación fija de material asignada permanentemente a un vehículo (PR3).
    DOTACION_VEHICULO = "dotacion_vehiculo"


class AsignacionMaterial(SQLModel, table=True):
    """Asignación de material a un voluntario, a un servicio o a un vehículo.

    Un material puede estar asignado a exactamente uno de:

    - un voluntario (PERSONAL / PRESTAMO): ``voluntario_id`` set, resto NULL;
    - un servicio (SERVICIO): ``servicio_id`` set, resto NULL;
    - un vehículo (DOTACION_VEHICULO): ``vehiculo_id`` set, resto NULL.

    El ``CheckConstraint`` ``ck_asignacion_material_target`` asegura que
    haya **exactamente un** destino (target ternario tipado): ni 0 (sin
    destino), ni 2 o 3 (ambigüedad).

    La asignación está **activa** mientras ``fecha_devolucion IS NULL``.
    Al devolver o al cerrar el servicio asociado se sella la fecha; la
    fila se conserva como histórico (soft delete operativo).

    **Dotación fija (PR3):** una fila ``tipo=DOTACION_VEHICULO`` con
    ``vehiculo_id`` set y ``fecha_devolucion=NULL`` permanente representa
    el material que viaja siempre con un vehículo. No se libera al cerrar
    un servicio (no tiene ``servicio_id``). Solo material PRESTABLE puede
    ser dotación fija.
    """

    __tablename__ = "asignaciones_material"

    __table_args__ = (
        CheckConstraint(
            "(voluntario_id IS NOT NULL)::int "
            "+ (servicio_id IS NOT NULL)::int "
            "+ (vehiculo_id IS NOT NULL)::int = 1",
            name="ck_asignacion_material_target",
        ),
    )

    id: uuid.UUID = pk_uuid()
    material_id: uuid.UUID = Field(foreign_key="materiales.id", index=True)
    voluntario_id: uuid.UUID | None = Field(
        default=None, foreign_key="voluntarios.id", index=True
    )
    servicio_id: uuid.UUID | None = Field(
        default=None, foreign_key="servicios.id", index=True
    )
    vehiculo_id: uuid.UUID | None = Field(
        default=None, foreign_key="vehiculos.id", index=True
    )
    tipo: TipoAsignacion = Field(
        sa_column=Column(
            SAEnum(
                TipoAsignacion,
                name="tipo_asignacion_material",
                create_constraint=True,
            ),
            nullable=False,
        ),
    )
    cantidad: int = Field(default=1, ge=1, nullable=False)
    fecha_asignacion: datetime
    fecha_devolucion: datetime | None = None
    observaciones_devolucion: str | None = None

    # Relaciones
    material: Optional["Material"] = Relationship(back_populates="asignaciones")
    voluntario: Optional["Voluntario"] = Relationship()
    servicio: Optional["Servicio"] = Relationship()
    vehiculo: Optional["Vehiculo"] = Relationship()

    @property
    def activa(self) -> bool:
        """True si la asignación sigue vigente (sin fecha de devolución)."""

        return self.fecha_devolucion is None

    def __repr__(self) -> str:
        if self.voluntario_id:
            objetivo = f"voluntario={self.voluntario_id}"
        elif self.servicio_id:
            objetivo = f"servicio={self.servicio_id}"
        else:
            objetivo = f"vehiculo={self.vehiculo_id}"
        return (
            f"<AsignacionMaterial material={self.material_id} {objetivo} "
            f"tipo={self.tipo.value} activa={self.activa}>"
        )
