"""Modelo de Material (Epic E05).

Cubre los CU-20 (registrar) y CU-24 (reportar avería/pérdida) y soporta
las US-05-01/03/05/06/08/09/10 desde BD. El modelo es deliberadamente
separado de :class:`Vehiculo` por dos razones:

1. Los campos divergen mucho: ``cantidad`` (Material) no aplica al
   vehículo (que es siempre cantidad=1 con identificador único), y
   ``matricula`` / ``fecha_itv`` (Vehiculo) no aplican al material.
2. Los permisos del RBAC del Sprint 3 ya cortan diferente:
   ``inventario.registrar_material`` (jefe_equipo+) vs
   ``inventario.registrar_vehiculo`` (jefe_unidad+, decisión 9 del
   documento RBAC por criticidad del activo).

Decisión de modelado: ``categoria`` es ``str`` libre. El backlog
mencionaba un modelo ``Categoria`` aparte pero ningún flujo de E05
requiere catálogo (no hay ``GET /categorias``, no hay validaciones
cross-entidad). Si emergen necesidades de catálogo se promoverá según
el patrón de ADR-025.
"""

import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Column
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import created_at_column, pk_uuid, updated_at_column

if TYPE_CHECKING:
    from app.models.asignacion_material import AsignacionMaterial


class TipoMaterial(enum.StrEnum):
    """Tipo de material según su política de asignación."""

    PERSONAL = "personal"
    PRESTABLE = "prestable"
    SERVICIO = "servicio"


class EstadoInventario(enum.StrEnum):
    """Estado del activo en el inventario (compartido por Material y Vehiculo)."""

    OPERATIVO = "operativo"
    AVERIADO = "averiado"
    PERDIDO = "perdido"
    EN_USO = "en_uso"


class Material(SQLModel, table=True):
    """Material o equipamiento del inventario."""

    __tablename__ = "materiales"

    id: uuid.UUID = pk_uuid()

    # Identificación
    nombre: str = Field(max_length=255)
    descripcion: str | None = None
    codigo: str | None = Field(default=None, max_length=255, unique=True)
    numero_serie: str | None = Field(default=None, max_length=255)

    # Clasificación
    tipo: TipoMaterial = Field(
        sa_column=Column(
            SAEnum(TipoMaterial, name="tipo_material", create_constraint=True),
            nullable=False,
        ),
    )
    categoria: str | None = Field(default=None, max_length=100)
    estado: EstadoInventario = Field(
        default=EstadoInventario.OPERATIVO,
        sa_column=Column(
            SAEnum(
                EstadoInventario,
                name="estado_inventario",
                create_constraint=True,
            ),
            nullable=False,
            default=EstadoInventario.OPERATIVO,
        ),
    )

    # Stock
    cantidad: int = Field(default=1, ge=0, nullable=False)
    # Ubicación: el texto queda como etiqueta legacy opcional; la
    # referencia canónica es el FK al catálogo `ubicaciones` (PR2). El
    # `ON DELETE RESTRICT` se aplica en la migración (no se borra una
    # ubicación en uso).
    ubicacion_base: str | None = Field(default=None, max_length=255)
    ubicacion_base_id: uuid.UUID | None = Field(
        default=None, foreign_key="ubicaciones.id", index=True
    )

    # Datos opcionales del CU-20
    fecha_adquisicion: date | None = None
    fecha_proxima_revision: date | None = None
    foto_url: str | None = Field(default=None, max_length=500)

    # Trazabilidad de incidencias (US-05-08 / US-05-09)
    observaciones_incidencia: str | None = None

    # Timestamps
    created_at: datetime | None = created_at_column()
    updated_at: datetime | None = updated_at_column()

    # Relaciones
    asignaciones: list["AsignacionMaterial"] = Relationship(
        back_populates="material"
    )

    def __repr__(self) -> str:
        return f"<Material {self.nombre!r} ({self.tipo.value}/{self.estado.value})>"
