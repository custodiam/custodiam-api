"""Modelo de Ubicacion — catálogo de ubicaciones físicas (E10 / PR2).

Promueve el ``ubicacion_base`` de texto libre de :class:`Material` y
:class:`Vehiculo` (hasta ahora ``str``) a un catálogo seleccionable. Cada
ubicación lleva, además del nombre y una descripción opcional, coordenadas
geográficas opcionales (``lat`` / ``lng``) que habilitan la futura capa de
mapas (ADR-030) sin re-migrar: la tabla nace con las columnas, vacías hasta
que el módulo de mapas las use.

El catálogo sigue el patrón de ADR-025 (tabla de instancias seleccionable,
sin discriminador ni JSONB: los campos son estables y comunes a toda
ubicación). El ``nombre`` es único para que el alta desde el picker no genere
duplicados. La FK ``ubicacion_base_id`` desde ``materiales`` / ``vehiculos``
se añade en una migración posterior (transición suave): este modelo es
autocontenido.

Permisos: escritura ``ubicaciones.crear`` (jefe_seccion+, RBAC v0.2.0); la
lectura reutiliza ``inventario.ver`` mientras el único consumidor sea el
inventario.
"""

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import created_at_column, pk_uuid, updated_at_column


class Ubicacion(SQLModel, table=True):
    """Ubicación física del catálogo (base, almacén, punto de servicio)."""

    __tablename__ = "ubicaciones"

    id: uuid.UUID = pk_uuid()

    nombre: str = Field(max_length=255, unique=True)
    descripcion: str | None = None

    # Coordenadas opcionales (prerrequisito de mapas, ADR-030). Nullable
    # desde el origen: el módulo de mapas las rellenará. "Ambos o ninguno"
    # y la validación de rango viven en Pydantic, no como CHECK en BD
    # (mismo criterio que el geo embebido de `Servicio`).
    lat: float | None = None
    lng: float | None = None

    created_at: datetime | None = created_at_column()
    updated_at: datetime | None = updated_at_column()

    def __repr__(self) -> str:
        return f"<Ubicacion {self.nombre!r}>"
