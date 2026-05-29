"""Modelo de Servicio (Epic E03).

Cubre los CU-01 (alta preventivo + flujo alternativo emergencia), CU-02
(publicación) y CU-07 (cierre). La máquina de estados vive en
`app/services/servicios.py` para que el modelo solo describa la forma
de los datos.

Decisiones de modelado tomadas en EN-03-01:

- ``TipoServicio`` es un enum cerrado (PREVENTIVO, EMERGENCIA,
  FORMACION, OTRO). No se aplica ADR-025 (catálogo extensible) porque
  ningún flujo de E03 introduce divergencia por sub-tipo dentro del
  mismo tipo; cuando aparezcan flujos divergentes se promoverá a
  catálogo en un enabler posterior.
- ``CategoriaServicio`` se difiere: el backlog la pide pero ninguna
  US-03 ni CU-01..07 introduce flujo distinto por categoría. Sin uso
  real, sería estado muerto. Se reabrirá cuando el dominio lo justifique.
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Column, func, select
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import column_property
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import created_at_column, pk_uuid, updated_at_column

if TYPE_CHECKING:
    from app.models.inscripcion_servicio import InscripcionServicio


class EstadoServicio(enum.StrEnum):
    """Estados de la máquina del servicio (EN-03-03)."""

    BORRADOR = "borrador"
    PUBLICADO = "publicado"
    ACTIVO = "activo"
    CERRADO = "cerrado"


class TipoServicio(enum.StrEnum):
    """Tipos de servicio. El flujo `emergencia` puede saltar directamente
    de BORRADOR a ACTIVO; el resto pasan por PUBLICADO obligatoriamente.
    """

    PREVENTIVO = "preventivo"
    EMERGENCIA = "emergencia"
    FORMACION = "formacion"
    OTRO = "otro"


class Servicio(SQLModel, table=True):
    """Servicio de la agrupación de Protección Civil."""

    __tablename__ = "servicios"

    id: uuid.UUID = pk_uuid()

    # Identificación funcional
    titulo: str = Field(max_length=255)
    descripcion: str | None = None
    tipo: TipoServicio = Field(
        sa_column=Column(
            SAEnum(TipoServicio, name="tipo_servicio", create_constraint=True),
            nullable=False,
        ),
    )
    estado: EstadoServicio = Field(
        default=EstadoServicio.BORRADOR,
        sa_column=Column(
            SAEnum(EstadoServicio, name="estado_servicio", create_constraint=True),
            nullable=False,
            default=EstadoServicio.BORRADOR,
        ),
    )

    # Programación
    fecha_inicio: datetime
    fecha_fin: datetime | None = None
    ubicacion: str = Field(max_length=255)

    # Coordenadas geográficas opcionales (PR2-geo, SP-09). Las aporta el
    # cliente; el backend solo persiste (sin geocoding server-side). Los
    # servicios históricos quedan a NULL, nunca 0.0. La validación de rango
    # y la regla "ambos o ninguno" viven en los schemas Pydantic, no como
    # CHECK en BD.
    ubicacion_lat: float | None = Field(default=None)
    ubicacion_lng: float | None = Field(default=None)

    # Datos opcionales del CU-01 paso 5
    numero_voluntarios: int | None = None
    notas_material: str | None = None
    notas_vehiculos: str | None = None
    observaciones_cierre: str | None = None

    # Trazabilidad
    creado_por_keycloak_id: str | None = Field(
        default=None, max_length=255, index=True
    )
    fecha_cierre: datetime | None = None

    # Timestamps
    created_at: datetime | None = created_at_column()
    updated_at: datetime | None = updated_at_column()

    # Relaciones
    inscripciones: list["InscripcionServicio"] = Relationship(
        back_populates="servicio"
    )

    def __repr__(self) -> str:
        return f"<Servicio {self.titulo!r} ({self.tipo.value}/{self.estado.value})>"


# El conteo de inscritos se expone como ``column_property`` con un
# subquery escalar correlacionado: un COUNT sobre `InscripcionServicio`
# que viaja embebido en cualquier `SELECT Servicio` (sin N+1) y se
# resuelve en lectura, no como columna física (Alembic NO genera DDL).
#
# Se declara fuera de la clase, tras importar `InscripcionServicio` en
# tiempo de ejecución, para no introducir un ciclo de importación: el
# modelo de inscripción ya importa `Servicio` bajo `TYPE_CHECKING`.
from app.models.inscripcion_servicio import InscripcionServicio  # noqa: E402

Servicio.inscritos_count = column_property(
    select(func.count(InscripcionServicio.id))
    .where(InscripcionServicio.servicio_id == Servicio.id)
    .correlate_except(InscripcionServicio)
    .scalar_subquery(),
    deferred=False,
)
