"""Modelo de VoluntarioEvento (EN-02-04 / US-02-06).

Audit log cross-módulo del voluntario. Cada cambio relevante sobre la
ficha o sobre los recursos asociados al voluntario (servicios, fichaje,
material, rol) genera una fila en esta tabla con:

- ``tipo_evento`` — enum cerrado con las once acciones consideradas en
  el alcance del MVP. El enum es deliberadamente cerrado: cualquier
  acción nueva debe pasar por una decisión arquitectónica explícita
  antes de ampliar la lista, no se admite ``OTRO``.
- ``payload`` — JSONB con la información contextual de la acción
  (servicio_id, material_id, rol asignado, etc.). JSONB y no JSON
  estricto para aprovechar índices GIN si en el futuro se filtra por
  contenido del payload.
- ``actor_keycloak_id`` — quién hizo la acción. Puede coincidir con el
  voluntario (self-service) o ser un mando. ``None`` cuando la acción
  es automática del sistema (p. ej. cierre de fichajes al cerrar
  servicio en US-04-05).
- ``created_at`` — timestamp con default ``now()``. Index compuesto
  ``(voluntario_id, created_at DESC)`` para que el listado paginado
  del historial sea barato.

El modelo expone una **relación a Voluntario solo en TYPE_CHECKING**
para no introducir back_populates: el histórico no se carga
automáticamente con la ficha del voluntario; se consulta vía el
endpoint dedicado del historial.
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import Column
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import created_at_column, pk_uuid

if TYPE_CHECKING:
    from app.models.voluntario import Voluntario


class TipoEventoVoluntario(enum.StrEnum):
    """Acciones registradas en el audit log del voluntario."""

    ALTA = "alta"
    BAJA = "baja"
    ANONIMIZACION = "anonimizacion"
    CAMBIO_ROL_ASIGNADO = "cambio_rol_asignado"
    CAMBIO_ROL_REVOCADO = "cambio_rol_revocado"
    FICHAJE_ENTRADA = "fichaje_entrada"
    FICHAJE_SALIDA = "fichaje_salida"
    INSCRIPCION_SERVICIO = "inscripcion_servicio"
    BAJA_INSCRIPCION = "baja_inscripcion"
    ASIGNACION_MATERIAL = "asignacion_material"
    DEVOLUCION_MATERIAL = "devolucion_material"


class VoluntarioEvento(SQLModel, table=True):
    """Audit log del voluntario (EN-02-04)."""

    __tablename__ = "voluntario_eventos"

    id: uuid.UUID = pk_uuid()
    voluntario_id: uuid.UUID = Field(
        foreign_key="voluntarios.id", index=True
    )
    tipo_evento: TipoEventoVoluntario = Field(
        sa_column=Column(
            SAEnum(
                TipoEventoVoluntario,
                name="tipo_evento_voluntario",
                create_constraint=True,
            ),
            nullable=False,
        ),
    )
    payload: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    actor_keycloak_id: str | None = Field(
        default=None, max_length=255, index=True
    )
    created_at: datetime | None = created_at_column()

    voluntario: Optional["Voluntario"] = Relationship()

    def __repr__(self) -> str:
        return (
            f"<VoluntarioEvento {self.tipo_evento.value} "
            f"voluntario={self.voluntario_id} at={self.created_at}>"
        )
