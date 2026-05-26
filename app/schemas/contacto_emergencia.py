"""Schemas Pydantic para ContactoEmergencia (ADR-025)."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ContactoEmergenciaBase(BaseModel):
    """Persona a contactar en caso de emergencia con el voluntario."""

    nombre: str = Field(max_length=255)
    telefono: str = Field(max_length=20)
    parentesco: str | None = Field(default=None, max_length=100)
    orden_preferencia: int = Field(default=1, ge=1, le=10)


class ContactoEmergenciaCreate(ContactoEmergenciaBase):
    """Schema para POST `/voluntarios/{id}/contactos-emergencia`."""

    # `voluntario_id` se inyecta desde el path param del endpoint.


class ContactoEmergenciaUpdate(BaseModel):
    """Schema para PATCH (todos los campos opcionales)."""

    nombre: str | None = Field(default=None, max_length=255)
    telefono: str | None = Field(default=None, max_length=20)
    parentesco: str | None = Field(default=None, max_length=100)
    orden_preferencia: int | None = Field(default=None, ge=1, le=10)


class ContactoEmergenciaResponse(ContactoEmergenciaBase):
    """Schema de respuesta — incluye id + voluntario_id."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    voluntario_id: UUID
