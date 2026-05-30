"""Service del catálogo de ubicaciones (E10 / PR2).

Lógica de dominio del CRUD de ``ubicaciones``: validación de unicidad del
nombre (el constraint de BD es el backstop ante carreras) y traducción a
excepciones de dominio que el router mapea a códigos HTTP.

Excepciones de dominio
----------------------

- :class:`UbicacionNoEncontrada` → 404
- :class:`UbicacionYaExiste` → 409 (nombre duplicado)
- :class:`UbicacionEnUso` → 409 (referenciada por material/vehículo)
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlmodel import Session

from app.repositories import ubicaciones as repo

if TYPE_CHECKING:
    from app.models.ubicacion import Ubicacion
    from app.schemas.ubicacion import UbicacionCreate, UbicacionUpdate


class UbicacionError(Exception):
    """Base de las excepciones de dominio del catálogo de ubicaciones."""


class UbicacionNoEncontrada(UbicacionError):  # noqa: N818 — castellano
    pass


class UbicacionYaExiste(UbicacionError):  # noqa: N818 — castellano
    """Ya existe una ubicación con ese nombre (US-05-12)."""


class UbicacionEnUso(UbicacionError):  # noqa: N818 — castellano
    """La ubicación está referenciada por algún material o vehículo (PR2)."""


def listar_ubicaciones(
    session: Session,
    *,
    skip: int = 0,
    limit: int = 50,
    q: str | None = None,
) -> tuple[list[Ubicacion], int]:
    return repo.list_ubicaciones(session, skip=skip, limit=limit, q=q)


def obtener_ubicacion(session: Session, ubicacion_id: uuid.UUID) -> Ubicacion:
    ubicacion = repo.get_ubicacion(session, ubicacion_id)
    if ubicacion is None:
        raise UbicacionNoEncontrada(str(ubicacion_id))
    return ubicacion


def crear_ubicacion(session: Session, data: UbicacionCreate) -> Ubicacion:
    """US-05-12. Rechaza nombres duplicados con un 409 explícito."""

    if repo.get_ubicacion_por_nombre(session, data.nombre) is not None:
        raise UbicacionYaExiste(data.nombre)
    payload = data.model_dump(exclude_unset=False)
    return repo.create_ubicacion(session, payload)


def actualizar_ubicacion(
    session: Session, ubicacion_id: uuid.UUID, data: UbicacionUpdate
) -> Ubicacion:
    ubicacion = obtener_ubicacion(session, ubicacion_id)
    patch = data.model_dump(exclude_unset=True)

    nuevo_nombre = patch.get("nombre")
    if nuevo_nombre is not None and nuevo_nombre != ubicacion.nombre:
        existente = repo.get_ubicacion_por_nombre(session, nuevo_nombre)
        if existente is not None and existente.id != ubicacion.id:
            raise UbicacionYaExiste(nuevo_nombre)

    return repo.update_ubicacion(session, ubicacion, patch)


def eliminar_ubicacion(session: Session, ubicacion_id: uuid.UUID) -> None:
    ubicacion = obtener_ubicacion(session, ubicacion_id)
    if repo.esta_en_uso(session, ubicacion_id):
        raise UbicacionEnUso(str(ubicacion_id))
    repo.delete_ubicacion(session, ubicacion)
