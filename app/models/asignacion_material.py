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
    from app.models.voluntario import Voluntario


class TipoAsignacion(enum.StrEnum):
    """Discriminador del flujo de asignación (CU-21 / CU-22)."""

    # Equipamiento personal fijo asignado al voluntario (US-05-03).
    PERSONAL = "personal"
    # Préstamo temporal a un voluntario, pendiente de devolución (US-05-04).
    PRESTAMO = "prestamo"
    # Material reservado para un servicio concreto (US-05-06).
    SERVICIO = "servicio"


class AsignacionMaterial(SQLModel, table=True):
    """Asignación de material a un voluntario o a un servicio.

    Un material puede estar asignado a:

    - un voluntario (PERSONAL / PRESTAMO): ``voluntario_id`` set,
      ``servicio_id`` NULL;
    - un servicio (SERVICIO): ``servicio_id`` set, ``voluntario_id`` NULL.

    El ``CheckConstraint`` ``ck_asignacion_material_target`` asegura que
    no haya filas con ambos NULL (sería una asignación sin destino) ni
    con ambos set (ambigüedad).

    La asignación está **activa** mientras ``fecha_devolucion IS NULL``.
    Al devolver o al cerrar el servicio asociado se sella la fecha; la
    fila se conserva como histórico (soft delete operativo).
    """

    __tablename__ = "asignaciones_material"

    __table_args__ = (
        CheckConstraint(
            "(voluntario_id IS NOT NULL) <> (servicio_id IS NOT NULL)",
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

    @property
    def activa(self) -> bool:
        """True si la asignación sigue vigente (sin fecha de devolución)."""

        return self.fecha_devolucion is None

    def __repr__(self) -> str:
        objetivo = (
            f"voluntario={self.voluntario_id}"
            if self.voluntario_id
            else f"servicio={self.servicio_id}"
        )
        return (
            f"<AsignacionMaterial material={self.material_id} {objetivo} "
            f"tipo={self.tipo.value} activa={self.activa}>"
        )
