"""Schemas Pydantic para Voluntario (CU-10, CU-11, CU-13, ADR-025).

Cubren los casos de uso de alta (CU-10), modificación admin (CU-11
flujo B), modificación self (CU-11 flujo A), y consulta self (CU-13).

Para las acreditaciones, tallas y contactos de emergencia que cuelgan
del voluntario, ver los módulos hermanos:
- `app.schemas.acreditacion`
- `app.schemas.equipamiento`
- `app.schemas.contacto_emergencia`
"""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.validators import fecha_no_futura
from app.models.voluntario import EstadoVoluntario
from app.schemas.acreditacion import AcreditacionResponse
from app.schemas.contacto_emergencia import ContactoEmergenciaResponse
from app.schemas.equipamiento import TallaVoluntarioResponse


class VoluntarioBase(BaseModel):
    """Campos comunes de un voluntario, editables por admin (CU-11 B)."""

    nombre: str = Field(max_length=255)
    telefono: str = Field(max_length=20)
    municipio: str = Field(max_length=100)
    fecha_nacimiento: date

    # Opcionales
    dni: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None
    direccion: str | None = Field(default=None, max_length=255)
    foto_url: str | None = None
    conductor_habilitado: bool = False


class VoluntarioCreate(VoluntarioBase):
    """Schema para POST `/voluntarios` — alta por admin (CU-10).

    `keycloak_id` y `fecha_alta` se inyectan en el servicio tras crear
    el usuario en Keycloak vía Admin API (EN-02-03). No se aceptan
    en el body para evitar inconsistencia con Keycloak.

    El `estado` se fija a `ACTIVO` por defecto en el modelo.
    """

    # Email OBLIGATORIO en el alta: es la llave del onboarding, ya que el
    # voluntario recibe en él la invitación de Keycloak para establecer su
    # contraseña. Se sobrescribe aquí (en `VoluntarioBase` es opcional
    # porque `VoluntarioResponse` y los schemas de update lo heredan y
    # deben tolerar valores nulos de voluntarios anteriores).
    email: EmailStr

    @field_validator("fecha_nacimiento")
    @classmethod
    def _fecha_nacimiento_no_futura(cls, v: date) -> date:
        return fecha_no_futura(v)


class VoluntarioUpdateAdmin(BaseModel):
    """Schema PATCH para admin (CU-11 B) — cualquier campo del modelo."""

    nombre: str | None = Field(default=None, max_length=255)
    telefono: str | None = Field(default=None, max_length=20)
    municipio: str | None = Field(default=None, max_length=100)
    fecha_nacimiento: date | None = None
    dni: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None
    direccion: str | None = Field(default=None, max_length=255)
    foto_url: str | None = None
    conductor_habilitado: bool | None = None
    estado: EstadoVoluntario | None = None
    fecha_baja: date | None = None


class VoluntarioUpdateSelf(BaseModel):
    """Schema PATCH para voluntario sobre sí mismo (CU-11 A).

    Solo permite editar datos de contacto. NO permite editar nombre,
    DNI, rol, estado, fecha_alta — esos son responsabilidad del admin
    (CU-11 B). Validación reforzada a nivel de endpoint (permission
    `voluntarios.editar_propio`).
    """

    telefono: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None
    municipio: str | None = Field(default=None, max_length=100)
    direccion: str | None = Field(default=None, max_length=255)
    foto_url: str | None = None


class VoluntarioSummary(BaseModel):
    """Schema de respuesta compacto para listas paginadas (CU-15)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nombre: str
    telefono: str
    municipio: str
    estado: EstadoVoluntario
    conductor_habilitado: bool


class VoluntarioResponse(VoluntarioBase):
    """Schema de respuesta completo (CU-13 + ficha admin CU-11 B).

    Incluye relaciones nested: acreditaciones, tallas, contactos
    emergencia. Los roles se exponen en el JWT del usuario, no
    duplicados aquí (ADR-013 RBAC lockstep).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    keycloak_id: str | None = None
    estado: EstadoVoluntario
    fecha_alta: date
    fecha_baja: date | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # Relaciones nested
    acreditaciones: list[AcreditacionResponse] = Field(default_factory=list)
    tallas: list[TallaVoluntarioResponse] = Field(default_factory=list)
    contactos_emergencia: list[ContactoEmergenciaResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Asignación de roles (EN-02-05)
# ---------------------------------------------------------------------------


class RolResponse(BaseModel):
    """Entrada del catálogo de roles para `GET /roles`.

    Pensado para que el cliente construya selectores de rol sin un
    segundo round-trip. No incluye ``permisos`` (campo JSONB del modelo)
    porque la matriz canónica vive en ``app/core/permissions.py`` y el
    cliente la espeja como ``Permission`` enum en
    ``custodiam-app/lib/infrastructure/auth/permissions.dart`` (lockstep
    ADR-013 RBAC). Exponerla aquí abriría puerta a divergencia.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nombre: str
    nivel: int
    descripcion: str | None = None


class AsignarRolRequest(BaseModel):
    """Body de ``POST /voluntarios/{id}/roles``."""

    rol_id: UUID


class VoluntarioRolResponse(BaseModel):
    """Respuesta de los endpoints de asignación/baja de rol.

    Expone tanto el ``rol_id`` (interno) como el ``rol_nombre`` (que es
    el que se sincroniza con Keycloak) para que el cliente no necesite
    un segundo round-trip al catálogo de roles tras la mutación.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    voluntario_id: UUID
    rol_id: UUID
    rol_nombre: str
    fecha_desde: date
    fecha_hasta: date | None = None
