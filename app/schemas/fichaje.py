"""Schemas Pydantic para Fichaje (EN-04-01).

Cubren los CU-05 (entrada), CU-06 (salida) y US-04-04 (lista de
voluntarios fichados en un servicio).
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FichajeResponse(BaseModel):
    """Schema de respuesta de un fichaje individual."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    servicio_id: UUID
    voluntario_id: UUID
    hora_entrada: datetime
    hora_salida: datetime | None = None
    automatico: bool
    duracion_segundos: int | None = None


class FichajeEnServicioResponse(BaseModel):
    """Schema aplanado para `GET /servicios/{id}/fichaje` (US-04-04).

    Incluye los datos mínimos del voluntario para que el jefe pueda
    identificar a cada persona sin un segundo round-trip.
    """

    model_config = ConfigDict(from_attributes=True)

    fichaje_id: UUID
    voluntario_id: UUID
    nombre: str
    hora_entrada: datetime
    hora_salida: datetime | None = None
    automatico: bool
    duracion_segundos: int | None = None


class HorasAcumuladasResponse(BaseModel):
    """Suma de horas computadas para un voluntario (US-04-03 amplía esto)."""

    voluntario_id: UUID
    total_segundos: int
    total_horas: float
    fichajes_cerrados: int
    fichajes_abiertos: int
