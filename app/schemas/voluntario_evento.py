"""Schemas Pydantic para VoluntarioEvento (EN-02-04 / US-02-06).

Cubren los dos endpoints del historial del voluntario:

- ``GET /api/v1/voluntarios/me/historial`` (lista paginada)
- ``GET /api/v1/voluntarios/me/resumen`` (agregado: horas + servicios)
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.voluntario_evento import TipoEventoVoluntario


class VoluntarioEventoResponse(BaseModel):
    """Una fila del audit log del voluntario."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    voluntario_id: UUID
    tipo_evento: TipoEventoVoluntario
    payload: dict[str, Any] | None = None
    actor_keycloak_id: str | None = None
    created_at: datetime | None = None


class UltimoServicioResumen(BaseModel):
    """Referencia compacta del último servicio del voluntario."""

    servicio_id: UUID
    titulo: str
    fecha_inicio: datetime


class ResumenVoluntarioResponse(BaseModel):
    """Resumen agregado del historial (CU-13, US-02-06).

    - ``segundos_totales`` se calcula sumando la duración de los fichajes
      cerrados del voluntario.
    - ``horas_totales`` es el cociente entero ``segundos_totales // 3600``
      para que el cliente lo pinte sin tener que reformatear.
    - ``servicios_realizados`` cuenta inscripciones (inscrito o convocado)
      en servicios cuyo estado es ``cerrado`` — un servicio cuenta cuando
      ya ha terminado, no cuando solo está publicado.
    - ``ultimo_servicio`` es ``None`` si el voluntario aún no ha
      participado en ningún servicio cerrado.
    """

    horas_totales: int = Field(ge=0)
    segundos_totales: int = Field(ge=0)
    servicios_realizados: int = Field(ge=0)
    ultimo_servicio: UltimoServicioResumen | None = None
