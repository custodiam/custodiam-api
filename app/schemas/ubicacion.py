"""Schemas Pydantic para el catálogo de Ubicaciones (E10 / PR2).

Promueve el ``ubicacion_base`` de texto libre de Material y Vehiculo a un
catálogo seleccionable. Las coordenadas ``lat`` / ``lng`` son opcionales
(prerrequisito de mapas, ADR-030) y se validan en Pydantic: rango y
"ambos o ninguno", igual que el geo embebido de Servicio.
"""

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _validar_coordenadas(lat: float | None, lng: float | None) -> None:
    """Valida las coordenadas geográficas opcionales (ADR-030).

    Reglas, intencionadamente en Pydantic y no como CHECK en BD:

    - Rango: ``lat`` ∈ [-90, 90], ``lng`` ∈ [-180, 180].
    - "Ambos o ninguno": no se admite fijar solo una de las dos.
    """

    if (lat is None) != (lng is None):
        raise ValueError("lat y lng deben enviarse juntos (ambos o ninguno)")
    if lat is not None and not -90.0 <= lat <= 90.0:
        raise ValueError("lat debe estar en el rango [-90, 90]")
    if lng is not None and not -180.0 <= lng <= 180.0:
        raise ValueError("lng debe estar en el rango [-180, 180]")


class UbicacionBase(BaseModel):
    """Campos editables comunes de una ubicación."""

    nombre: str = Field(max_length=255, min_length=1)
    descripcion: str | None = None
    lat: float | None = None
    lng: float | None = None

    @model_validator(mode="after")
    def _check_coordenadas(self) -> Self:
        _validar_coordenadas(self.lat, self.lng)
        return self


class UbicacionCreate(UbicacionBase):
    """Schema para POST `/ubicaciones` (US-05-12, permiso ubicaciones.crear)."""


class UbicacionUpdate(BaseModel):
    """Schema PATCH — todos los campos opcionales.

    La validación "ambos o ninguno" sigue aplicando sobre los campos
    enviados: tocar una coordenada obliga a enviar la otra. El service
    aplica el patch con ``exclude_unset=True`` para no machacar columnas
    no enviadas.
    """

    nombre: str | None = Field(default=None, max_length=255, min_length=1)
    descripcion: str | None = None
    lat: float | None = None
    lng: float | None = None

    @model_validator(mode="after")
    def _check_coordenadas(self) -> Self:
        _validar_coordenadas(self.lat, self.lng)
        return self


class UbicacionSummary(BaseModel):
    """Schema compacto para el picker y las listas paginadas (US-05-12)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nombre: str
    lat: float | None = None
    lng: float | None = None


class UbicacionResponse(UbicacionBase):
    """Schema de detalle de una ubicación."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
