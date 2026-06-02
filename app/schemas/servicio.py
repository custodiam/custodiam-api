"""Schemas Pydantic para Servicio e InscripcionServicio (EN-03-01).

Cubren los CU-01 (alta preventivo + flujo emergencia), CU-02 (publicar),
CU-03 (convocar), CU-04 (apuntarse / desapuntarse) y CU-07 (cerrar).
"""

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.inscripcion_servicio import TipoInscripcion
from app.models.servicio import EstadoServicio, TipoServicio

# ---------------------------------------------------------------------------
# Servicio
# ---------------------------------------------------------------------------


def _validar_coordenadas(lat: float | None, lng: float | None) -> None:
    """Valida las coordenadas geográficas opcionales (PR2-geo, SP-09).

    Reglas, intencionadamente en Pydantic y no como CHECK en BD:

    - Rango: ``lat`` ∈ [-90, 90], ``lng`` ∈ [-180, 180].
    - "Ambos o ninguno": no se admite fijar solo una de las dos.
    """

    if (lat is None) != (lng is None):
        raise ValueError(
            "ubicacion_lat y ubicacion_lng deben enviarse juntos "
            "(ambos o ninguno)"
        )
    if lat is not None and not -90.0 <= lat <= 90.0:
        raise ValueError("ubicacion_lat debe estar en el rango [-90, 90]")
    if lng is not None and not -180.0 <= lng <= 180.0:
        raise ValueError("ubicacion_lng debe estar en el rango [-180, 180]")


class ServicioBase(BaseModel):
    """Campos editables comunes de un servicio."""

    titulo: str = Field(max_length=255)
    descripcion: str | None = None
    tipo: TipoServicio
    fecha_inicio: datetime
    fecha_fin: datetime | None = None
    ubicacion: str = Field(max_length=255)
    ubicacion_lat: float | None = None
    ubicacion_lng: float | None = None
    numero_voluntarios: int | None = Field(default=None, ge=0)
    notas_material: str | None = None
    notas_vehiculos: str | None = None

    @model_validator(mode="after")
    def _check_coordenadas(self) -> Self:
        _validar_coordenadas(self.ubicacion_lat, self.ubicacion_lng)
        return self


class ServicioCreate(ServicioBase):
    """Schema para POST `/servicios` (CU-01).

    El estado inicial lo decide el servicio:

    - ``preventivo`` / ``formacion`` / ``otro`` → ``borrador``.
    - ``emergencia`` → ``activo`` directamente (CU-01 flujo alternativo).

    El cliente NO envía ``estado``: viene determinado por ``tipo``.
    """


class ServicioUpdate(BaseModel):
    """Schema PATCH para servicios. Todos los campos opcionales.

    No incluye ``estado`` porque las transiciones se hacen por endpoints
    específicos (``/publicar``, ``/convocar``, ``/cerrar``). Permitir
    cambiar el estado por PATCH eludiría la máquina de estados.
    """

    titulo: str | None = Field(default=None, max_length=255)
    descripcion: str | None = None
    tipo: TipoServicio | None = None
    fecha_inicio: datetime | None = None
    fecha_fin: datetime | None = None
    ubicacion: str | None = Field(default=None, max_length=255)
    ubicacion_lat: float | None = None
    ubicacion_lng: float | None = None
    numero_voluntarios: int | None = Field(default=None, ge=0)
    notas_material: str | None = None
    notas_vehiculos: str | None = None

    @model_validator(mode="after")
    def _check_coordenadas(self) -> Self:
        _validar_coordenadas(self.ubicacion_lat, self.ubicacion_lng)
        return self


class ServicioCerrar(BaseModel):
    """Body opcional del cierre (CU-07).

    Los datos oficiales que el CU-07 marca como obligatorios (vehículos,
    voluntarios intervinientes) viven en otras entidades del sistema
    (`InscripcionServicio` para los voluntarios; el inventario para
    los vehículos llegará en E05). En el alcance de E03, el cierre se
    limita a observaciones libres.
    """

    observaciones_cierre: str | None = None


class ServicioConvocar(BaseModel):
    """Body opcional del POST `/servicios/{id}/convocar` (CU-03).

    Si ``voluntario_ids`` viene vacío o ausente, equivale a "convocar
    a todos los activos disponibles" (US-03-04). Si se especifican
    ids, solo se convoca a esos (US-03-05). En cualquier caso, la
    convocatoria registra ``InscripcionServicio`` con
    ``tipo=convocado`` y deja el servicio en estado ``activo``.

    Nota: el envío de notificaciones push (Firebase FCM) NO se ejecuta
    aquí — vive en E06 (Notificaciones), fuera del scope de E03.
    """

    voluntario_ids: list[UUID] = Field(default_factory=list)


class ServicioSummary(BaseModel):
    """Schema compacto para listas paginadas (US-03-07)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    titulo: str
    tipo: TipoServicio
    estado: EstadoServicio
    fecha_inicio: datetime
    fecha_fin: datetime | None = None
    ubicacion: str
    ubicacion_lat: float | None = None
    ubicacion_lng: float | None = None
    numero_voluntarios: int | None = None
    inscritos_count: int = 0


class ServicioResponse(ServicioBase):
    """Schema de respuesta completo."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    estado: EstadoServicio
    inscritos_count: int = 0
    observaciones_cierre: str | None = None
    creado_por_keycloak_id: str | None = None
    fecha_cierre: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# InscripcionServicio
# ---------------------------------------------------------------------------


class InscripcionServicioResponse(BaseModel):
    """Schema de respuesta para una inscripción individual."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    servicio_id: UUID
    voluntario_id: UUID
    tipo: TipoInscripcion
    fecha: datetime


class VoluntarioInscritoResponse(BaseModel):
    """Schema agregado para `GET /servicios/{id}/voluntarios`.

    Aplana la asociación a un único objeto por voluntario, exponiendo
    los campos mínimos para identificarlo y diferenciar si llegó por
    inscripción propia o por convocatoria.
    """

    model_config = ConfigDict(from_attributes=True)

    voluntario_id: UUID
    nombre: str
    telefono: str
    tipo: TipoInscripcion
    fecha: datetime
