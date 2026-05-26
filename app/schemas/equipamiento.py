"""Schemas Pydantic para TipoEquipamiento y TallaVoluntario (ADR-025)."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TipoEquipamientoResponse(BaseModel):
    """Tipo del catálogo de equipamiento (solo lectura).

    Pre-poblado vía Alembic data migration con los items canónicos
    (CAMISA, POLO, CHAQUETA, PANTALON, BOTAS, CASCO, GUANTES, CHALECO).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    codigo: str
    nombre: str
    sistema_tallas: str | None = None
    activo: bool


class TallaVoluntarioBase(BaseModel):
    """Talla declarada por un voluntario para un tipo de equipamiento."""

    tipo_id: UUID
    valor: str = Field(max_length=20)


class TallaVoluntarioCreate(TallaVoluntarioBase):
    """Schema para POST `/voluntarios/{id}/tallas`."""

    # `voluntario_id` se inyecta desde el path param del endpoint.


class TallaVoluntarioUpdate(BaseModel):
    """Schema para PATCH (solo el valor es editable)."""

    valor: str | None = Field(default=None, max_length=20)


class TallaVoluntarioResponse(TallaVoluntarioBase):
    """Schema de respuesta — incluye id + voluntario_id + tipo expandido."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    voluntario_id: UUID
    tipo: TipoEquipamientoResponse | None = None
