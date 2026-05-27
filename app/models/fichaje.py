"""Modelo de Fichaje (Epic E04).

Cubre los CU-05 (fichar entrada) y CU-06 (fichar salida). El flujo
operativo es: el voluntario debe estar inscrito o convocado en un
servicio activo, ficha su entrada, y al terminar ficha su salida. Si
el servicio se cierra antes de que ficha su salida, el sistema lo
ficha automáticamente con `automatico=True` y `hora_salida = fecha de
cierre del servicio` (US-04-05).

Decisiones de modelado:

- ``UNIQUE(servicio_id, voluntario_id)``: un voluntario solo tiene un
  fichaje por servicio. Si quiere "salir y volver", la realidad
  operativa es marcar salida y dejar constancia — no doble entrada.
- ``hora_salida`` nullable: mientras es ``None`` el voluntario sigue
  en servicio. Se calcula la duración al setearla.
- ``automatico`` por defecto ``False``: solo se pone a ``True`` cuando
  el cierre del servicio fuerza la salida (US-04-05).
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import created_at_column, pk_uuid, updated_at_column

if TYPE_CHECKING:
    from app.models.servicio import Servicio
    from app.models.voluntario import Voluntario


class Fichaje(SQLModel, table=True):
    """Registro de entrada/salida de un voluntario en un servicio."""

    __tablename__ = "fichajes"

    __table_args__ = (
        UniqueConstraint(
            "servicio_id",
            "voluntario_id",
            name="uq_fichaje_servicio_voluntario",
        ),
    )

    id: uuid.UUID = pk_uuid()
    servicio_id: uuid.UUID = Field(foreign_key="servicios.id", index=True)
    voluntario_id: uuid.UUID = Field(foreign_key="voluntarios.id", index=True)
    hora_entrada: datetime
    hora_salida: datetime | None = None
    automatico: bool = Field(default=False, nullable=False)

    created_at: datetime | None = created_at_column()
    updated_at: datetime | None = updated_at_column()

    # Relaciones
    servicio: Optional["Servicio"] = Relationship()
    voluntario: Optional["Voluntario"] = Relationship()

    @property
    def duracion_segundos(self) -> int | None:
        """Duración del fichaje en segundos. ``None`` mientras sin salida."""

        if self.hora_salida is None:
            return None
        return int((self.hora_salida - self.hora_entrada).total_seconds())

    def __repr__(self) -> str:
        return (
            f"<Fichaje servicio={self.servicio_id} "
            f"voluntario={self.voluntario_id} "
            f"entrada={self.hora_entrada} salida={self.hora_salida}>"
        )
