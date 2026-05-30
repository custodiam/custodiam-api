"""Schemas Pydantic para el módulo de Inventario (Epic E05).

Cubre CU-20 (alta material/vehículo), CU-21 (asignar material a
voluntario), CU-22 (asignar a servicio), CU-23 (devolución) y CU-24
(reportar avería/pérdida).
"""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.asignacion_material import TipoAsignacion
from app.models.material import EstadoInventario, TipoMaterial
from app.models.vehiculo import TipoVehiculo

# ---------------------------------------------------------------------------
# Trazabilidad del estado actual (PR1) — sólo en responses de DETALLE
# ---------------------------------------------------------------------------


class AsignacionActualResponse(BaseModel):
    """Vista curada de "dónde está / a quién está asignado" un activo (PR1).

    Esquema unificado para las dos lecturas de trazabilidad:

    - **Material** (puede tener varias activas a la vez): cada entrada
      lleva su ``tipo`` (PERSONAL / PRESTAMO / SERVICIO / DOTACION_VEHICULO),
      el target correspondiente (uno de ``voluntario_id`` / ``servicio_id``
      / ``vehiculo_id``), la ``cantidad`` y la ``fecha_asignacion``.
    - **Vehículo** (unidad única, asignación singular): ``tipo`` es siempre
      ``"servicio"``, ``servicio_id`` está set, ``cantidad`` es 1 y se
      adjunta ``servicio_titulo`` (barato vía join, evita un segundo viaje).

    Decisión MVP (PO): no se expone ``fecha_devolucion_prevista``.
    """

    tipo: str
    voluntario_id: UUID | None = None
    servicio_id: UUID | None = None
    vehiculo_id: UUID | None = None
    servicio_titulo: str | None = None
    cantidad: int = 1
    fecha_asignacion: datetime


# ---------------------------------------------------------------------------
# Material
# ---------------------------------------------------------------------------


class MaterialBase(BaseModel):
    """Campos editables comunes de un material (CU-20 flujo principal)."""

    nombre: str = Field(max_length=255)
    descripcion: str | None = None
    codigo: str | None = Field(default=None, max_length=255)
    numero_serie: str | None = Field(default=None, max_length=255)
    tipo: TipoMaterial
    categoria: str | None = Field(default=None, max_length=100)
    cantidad: int = Field(default=1, ge=0)
    # Ubicación: texto legacy opcional + FK canónico al catálogo (PR2).
    ubicacion_base: str | None = Field(default=None, max_length=255)
    ubicacion_base_id: UUID | None = None
    fecha_adquisicion: date | None = None
    fecha_proxima_revision: date | None = None
    foto_url: str | None = Field(default=None, max_length=500)


class MaterialCreate(MaterialBase):
    """Schema para POST `/inventario/material` (CU-20, US-05-01).

    ``estado`` no se acepta del body; siempre arranca ``OPERATIVO``
    según CU-20 paso 7 + US-05-01.
    """


class MaterialUpdate(BaseModel):
    """Schema PATCH — todos los campos opcionales.

    No incluye ``estado``: las transiciones se hacen por endpoints
    específicos (``/incidencia``) o por flujo (asignación / devolución).
    """

    nombre: str | None = Field(default=None, max_length=255)
    descripcion: str | None = None
    codigo: str | None = Field(default=None, max_length=255)
    numero_serie: str | None = Field(default=None, max_length=255)
    tipo: TipoMaterial | None = None
    categoria: str | None = Field(default=None, max_length=100)
    cantidad: int | None = Field(default=None, ge=0)
    ubicacion_base: str | None = Field(default=None, max_length=255)
    ubicacion_base_id: UUID | None = None
    fecha_adquisicion: date | None = None
    fecha_proxima_revision: date | None = None
    foto_url: str | None = Field(default=None, max_length=500)


class IncidenciaMaterialRequest(BaseModel):
    """Body de `POST /inventario/material/{id}/incidencia` (CU-24)."""

    tipo: EstadoInventario = Field(
        description="Estado destino: AVERIADO o PERDIDO",
    )
    descripcion: str = Field(min_length=1)


class MaterialSummary(BaseModel):
    """Schema compacto para listas paginadas (US-05-10)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nombre: str
    codigo: str | None = None
    tipo: TipoMaterial
    categoria: str | None = None
    estado: EstadoInventario
    cantidad: int
    ubicacion_base: str | None = None
    ubicacion_base_id: UUID | None = None


class MaterialResponse(MaterialBase):
    """Schema de respuesta completo (DETALLE).

    Incluye la trazabilidad de PR1 (``asignaciones_activas`` +
    ``unidades_asignadas``). Estos campos NO viven en
    :class:`MaterialSummary` para no disparar N+1 en el listado.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    estado: EstadoInventario
    observaciones_incidencia: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    asignaciones_activas: list[AsignacionActualResponse] = Field(
        default_factory=list
    )
    unidades_asignadas: int = 0


# ---------------------------------------------------------------------------
# Vehiculo
# ---------------------------------------------------------------------------


class VehiculoBase(BaseModel):
    """Campos editables comunes de un vehículo (CU-20 flujo A)."""

    codigo_interno: str = Field(max_length=255)
    matricula: str = Field(max_length=255)
    tipo: TipoVehiculo
    marca_modelo: str | None = Field(default=None, max_length=255)
    fecha_itv: date | None = None
    foto_url: str | None = Field(default=None, max_length=500)
    observaciones: str | None = None
    # Ubicación: texto legacy opcional + FK canónico al catálogo (PR2).
    ubicacion_base: str | None = Field(default=None, max_length=255)
    ubicacion_base_id: UUID | None = None


class VehiculoCreate(VehiculoBase):
    """Schema para POST `/inventario/vehiculos` (CU-20, US-05-02)."""


class VehiculoUpdate(BaseModel):
    """Schema PATCH — todos los campos opcionales (sin tocar ``estado``)."""

    codigo_interno: str | None = Field(default=None, max_length=255)
    matricula: str | None = Field(default=None, max_length=255)
    tipo: TipoVehiculo | None = None
    marca_modelo: str | None = Field(default=None, max_length=255)
    fecha_itv: date | None = None
    foto_url: str | None = Field(default=None, max_length=500)
    observaciones: str | None = None
    ubicacion_base: str | None = Field(default=None, max_length=255)
    ubicacion_base_id: UUID | None = None


class IncidenciaVehiculoRequest(BaseModel):
    """Body de `POST /inventario/vehiculos/{id}/incidencia` (CU-24)."""

    tipo: EstadoInventario = Field(
        description="Estado destino: AVERIADO o PERDIDO",
    )
    descripcion: str = Field(min_length=1)


class VehiculoSummary(BaseModel):
    """Schema compacto para listas paginadas (US-05-10)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    codigo_interno: str
    matricula: str
    tipo: TipoVehiculo
    estado: EstadoInventario
    ubicacion_base: str | None = None
    ubicacion_base_id: UUID | None = None


class VehiculoResponse(VehiculoBase):
    """Schema de respuesta completo (DETALLE).

    Incluye ``asignacion_actual`` (PR1): la asignación a servicio activa
    del vehículo o ``None``. No vive en :class:`VehiculoSummary` para no
    disparar N+1 en el listado.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    estado: EstadoInventario
    observaciones_incidencia: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    asignacion_actual: AsignacionActualResponse | None = None


# ---------------------------------------------------------------------------
# Asignaciones
# ---------------------------------------------------------------------------


class AsignarMaterialVoluntarioRequest(BaseModel):
    """Body de `POST /inventario/material/{id}/asignar` (CU-21).

    Asigna material a un voluntario en modo PERSONAL (US-05-03) o
    PRESTAMO (US-05-04). El campo ``tipo`` es obligatorio para que el
    cliente sea explícito sobre el flujo (fijo vs temporal).
    """

    voluntario_id: UUID
    tipo: TipoAsignacion = Field(
        description="PERSONAL (fijo) o PRESTAMO (temporal)",
    )
    cantidad: int = Field(default=1, ge=1)


class DevolverMaterialRequest(BaseModel):
    """Body de `POST /inventario/material/{id}/devolver` (CU-23)."""

    voluntario_id: UUID
    observaciones: str | None = None


class AsignarMaterialServicioRequest(BaseModel):
    """Body de `POST /servicios/{id}/inventario/material` (CU-22, US-05-06)."""

    material_id: UUID
    cantidad: int = Field(default=1, ge=1)


class AsignarVehiculoServicioRequest(BaseModel):
    """Body de `POST /servicios/{id}/inventario/vehiculo` (CU-22, US-05-07)."""

    vehiculo_id: UUID


class AsignacionMaterialResponse(BaseModel):
    """Schema de respuesta de una asignación de material."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    material_id: UUID
    voluntario_id: UUID | None = None
    servicio_id: UUID | None = None
    tipo: TipoAsignacion
    cantidad: int
    fecha_asignacion: datetime
    fecha_devolucion: datetime | None = None
    observaciones_devolucion: str | None = None
    activa: bool


class AsignarDotacionVehiculoRequest(BaseModel):
    """Body de `POST /inventario/vehiculos/{id}/dotacion` (PR3).

    Asigna material PRESTABLE como dotación fija de un vehículo. El
    ``vehiculo_id`` viaja en la ruta, no en el body.
    """

    material_id: UUID
    cantidad: int = Field(default=1, ge=1)


class DotacionVehiculoResponse(BaseModel):
    """Vista curada de una dotación fija de vehículo (PR3).

    No expone el ``AsignacionMaterial`` crudo (con los tres targets
    mezclados): sólo los campos relevantes para el cliente, aplanando el
    nombre del material para evitar un segundo viaje al servidor.
    """

    id: UUID
    material_id: UUID
    material_nombre: str
    cantidad: int
    fecha_asignacion: datetime


class AsignacionVehiculoResponse(BaseModel):
    """Schema de respuesta de una asignación de vehículo."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    vehiculo_id: UUID
    servicio_id: UUID
    fecha_asignacion: datetime
    fecha_devolucion: datetime | None = None
    observaciones: str | None = None
    activa: bool


# ---------------------------------------------------------------------------
# Inventario de un servicio (lectura — R1 / Opción 1B)
# ---------------------------------------------------------------------------


class InventarioMaterialServicioResponse(BaseModel):
    """Material asignado a un servicio (lectura, R1).

    Aplana el nombre del material para evitar un segundo viaje al servidor,
    siguiendo el mismo patrón curado que :class:`DotacionVehiculoResponse`.
    """

    id: UUID
    material_id: UUID
    material_nombre: str
    cantidad: int
    fecha_asignacion: datetime


class InventarioVehiculoServicioResponse(BaseModel):
    """Vehículo asignado a un servicio (lectura, R1).

    Aplana los identificadores del vehículo (código interno y matrícula)
    para que la ficha del servicio los muestre sin resolverlos aparte.
    """

    id: UUID
    vehiculo_id: UUID
    codigo_interno: str
    matricula: str
    fecha_asignacion: datetime


class InventarioServicioResponse(BaseModel):
    """Recursos asignados a un servicio: material + vehículos.

    Respuesta de ``GET /servicios/{id}/inventario`` (R1, lectura). El POST
    de asignar ya existía; este GET cubre el lado de consulta.
    """

    material: list[InventarioMaterialServicioResponse]
    vehiculos: list[InventarioVehiculoServicioResponse]


# ---------------------------------------------------------------------------
# Ocupación / disponibilidad temporal de recursos (PR6 / Política A)
# ---------------------------------------------------------------------------


class ConflictoOcupacion(BaseModel):
    """Un servicio que reserva el recurso y solapa el intervalo consultado.

    El nombre ``ocupacion`` evita la colisión semántica con la
    "disponibilidad" del voluntario (calendario mensual, módulo E02): aquí
    se trata de la ocupación temporal de un activo de inventario por
    servicios concretos.
    """

    servicio_id: UUID
    fecha_inicio: datetime
    fecha_fin: datetime | None = None


class OcupacionRecursoResponse(BaseModel):
    """Respuesta de ``GET .../ocupacion?desde=&hasta=`` (PR6).

    - ``disponible``: ``True`` si el recurso puede comprometerse en el
      intervalo ``[desde, hasta)`` sin colisión (vehículo: sin solape;
      material: con stock suficiente tras descontar lo reservado por
      servicios solapados).
    - ``conflictos``: servicios que reservan el recurso y solapan el
      intervalo. En material puede haber conflictos y seguir ``disponible``
      si el stock alcanza.
    """

    disponible: bool
    conflictos: list[ConflictoOcupacion] = Field(default_factory=list)
