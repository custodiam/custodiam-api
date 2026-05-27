"""Schemas Pydantic para Disponibilidad (US-02-04 / CU-12).

Cubren los dos endpoints REST que el frontend consume para gestionar el
calendario mensual de disponibilidad del propio voluntario:

- ``GET /api/v1/voluntarios/me/disponibilidad?year=YYYY&month=MM``
- ``PUT /api/v1/voluntarios/me/disponibilidad/{fecha}`` (toggle).
"""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DisponibilidadResponse(BaseModel):
    """Una fila de la tabla ``disponibilidades``.

    El cliente la usa para pintar el calendario: si un día no aparece
    en la lista, se renderiza como ``no disponible`` por defecto.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    voluntario_id: UUID
    fecha: date
    disponible: bool


class DisponibilidadUpsertRequest(BaseModel):
    """Body del ``PUT /voluntarios/me/disponibilidad/{fecha}``.

    Idempotente: si la fila no existe se crea, si existe se actualiza el
    flag ``disponible``. No expone ``voluntario_id`` ni ``fecha``: el
    voluntario se resuelve desde el JWT y la fecha viene en el path.
    """

    disponible: bool


class DisponibilidadMesResponse(BaseModel):
    """Respuesta del GET mensual con el contexto temporal explícito.

    Aporta ``year`` y ``month`` para que el cliente no tenga que
    deducirlos del request: facilita renderizar la cabecera del
    calendario y detectar respuestas desfasadas si el usuario navega
    rápido entre meses.
    """

    year: int
    month: int
    dias: list[DisponibilidadResponse]
