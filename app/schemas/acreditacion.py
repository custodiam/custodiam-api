"""Schemas Pydantic para Acreditacion y TipoAcreditacion (ADR-025)."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.tipo_acreditacion import CategoriaAcreditacion


class TipoAcreditacionResponse(BaseModel):
    """Tipo del catálogo (solo lectura).

    El catálogo se gestiona vía Alembic data migration, no vía API.
    Por eso solo exponemos un schema de lectura.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    codigo: str
    nombre: str
    descripcion: str | None = None
    categoria: CategoriaAcreditacion
    campos_schema: dict | None = None
    activo: bool


class AcreditacionBase(BaseModel):
    """Campos comunes de una acreditación, editables por POST/PATCH."""

    tipo_id: UUID
    categoria: CategoriaAcreditacion
    fecha_obtencion: date
    fecha_caducidad: date | None = None
    numero: str | None = Field(default=None, max_length=100)
    entidad_emisora: str | None = Field(default=None, max_length=255)
    datos_especificos: dict | None = None
    documento_url: str | None = Field(default=None, max_length=500)


class AcreditacionCreate(AcreditacionBase):
    """Schema para POST `/voluntarios/{id}/acreditaciones`."""

    # `voluntario_id` se inyecta desde el path param del endpoint, no
    # se acepta en el body para evitar mismatch con la ruta.


class AcreditacionUpdate(BaseModel):
    """Schema para PATCH (todos los campos opcionales)."""

    tipo_id: UUID | None = None
    categoria: CategoriaAcreditacion | None = None
    fecha_obtencion: date | None = None
    fecha_caducidad: date | None = None
    numero: str | None = Field(default=None, max_length=100)
    entidad_emisora: str | None = Field(default=None, max_length=255)
    datos_especificos: dict | None = None
    documento_url: str | None = Field(default=None, max_length=500)


class AcreditacionResponse(AcreditacionBase):
    """Schema de respuesta — incluye id + voluntario_id + tipo expandido."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    voluntario_id: UUID
    tipo: TipoAcreditacionResponse | None = None
