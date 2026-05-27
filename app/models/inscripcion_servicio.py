"""Modelo de InscripcionServicio (EN-03-04).

Relación voluntario ↔ servicio con un discriminador `tipo` que distingue
las dos vías de entrada del CU-04 (apuntarse voluntariamente) y del
CU-03 (ser convocado por un mando). Un voluntario solo puede tener una
inscripción por servicio: si un convocado decide apuntarse por su cuenta
o viceversa, se actualiza el `tipo` existente.
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import pk_uuid

if TYPE_CHECKING:
    from app.models.servicio import Servicio
    from app.models.voluntario import Voluntario


class TipoInscripcion(enum.StrEnum):
    """Forma en que un voluntario entra al servicio.

    - ``INSCRITO``: el voluntario se apuntó por su cuenta (CU-04).
    - ``CONVOCADO``: un mando lo movilizó (CU-03).
    """

    INSCRITO = "inscrito"
    CONVOCADO = "convocado"


class InscripcionServicio(SQLModel, table=True):
    """Asociación voluntario ↔ servicio."""

    __tablename__ = "inscripciones_servicio"

    __table_args__ = (
        UniqueConstraint(
            "servicio_id",
            "voluntario_id",
            name="uq_inscripcion_servicio_voluntario",
        ),
    )

    id: uuid.UUID = pk_uuid()
    servicio_id: uuid.UUID = Field(foreign_key="servicios.id", index=True)
    voluntario_id: uuid.UUID = Field(foreign_key="voluntarios.id", index=True)
    tipo: TipoInscripcion = Field(
        sa_column=Column(
            SAEnum(TipoInscripcion, name="tipo_inscripcion", create_constraint=True),
            nullable=False,
        ),
    )
    fecha: datetime

    # Relaciones
    servicio: Optional["Servicio"] = Relationship(back_populates="inscripciones")
    voluntario: Optional["Voluntario"] = Relationship()

    def __repr__(self) -> str:
        return (
            f"<InscripcionServicio servicio={self.servicio_id} "
            f"voluntario={self.voluntario_id} tipo={self.tipo.value}>"
        )
