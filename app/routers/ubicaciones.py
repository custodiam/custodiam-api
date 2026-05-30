"""Router del catálogo de ubicaciones (E10 / PR2).

CRUD de ``/ubicaciones``: promueve el ``ubicacion_base`` de texto libre de
Material y Vehiculo a un catálogo seleccionable que alimenta el picker del
frontend (US-05-12).

RBAC: la escritura (crear / editar / borrar) exige ``ubicaciones.crear``
(jefe_seccion+, RBAC v0.2.0). La lectura reutiliza ``inventario.ver``
mientras el único consumidor sea el inventario.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session

from app.core.database import get_session
from app.core.permissions import Permission
from app.core.security import require_permission
from app.schemas.auth import CurrentUser
from app.schemas.ubicacion import (
    UbicacionCreate,
    UbicacionResponse,
    UbicacionSummary,
    UbicacionUpdate,
)
from app.services import ubicaciones as service

router = APIRouter(prefix="/ubicaciones", tags=["ubicaciones"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get(
    "",
    response_model=list[UbicacionSummary],
    summary="Listar ubicaciones del catálogo (US-05-12)",
)
def listar_ubicaciones(
    response: Response,
    session: SessionDep,
    _: Annotated[
        CurrentUser, Depends(require_permission(Permission.INVENTARIO_VER))
    ],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    q: str | None = Query(None, description="Búsqueda por nombre"),
):
    items, total = service.listar_ubicaciones(session, skip=skip, limit=limit, q=q)
    response.headers["X-Total-Count"] = str(total)
    return items


@router.get(
    "/{ubicacion_id}",
    response_model=UbicacionResponse,
    summary="Ver ficha de una ubicación",
)
def obtener_ubicacion(
    ubicacion_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[
        CurrentUser, Depends(require_permission(Permission.INVENTARIO_VER))
    ],
):
    try:
        return service.obtener_ubicacion(session, ubicacion_id)
    except service.UbicacionNoEncontrada as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ubicación no encontrada: {e}",
        ) from e


@router.post(
    "",
    response_model=UbicacionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear ubicación en el catálogo (US-05-12)",
)
def crear_ubicacion(
    data: UbicacionCreate,
    session: SessionDep,
    _: Annotated[
        CurrentUser, Depends(require_permission(Permission.UBICACIONES_CREAR))
    ],
):
    try:
        return service.crear_ubicacion(session, data)
    except service.UbicacionYaExiste as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe una ubicación con el nombre: {e}",
        ) from e


@router.patch(
    "/{ubicacion_id}",
    response_model=UbicacionResponse,
    summary="Modificar ubicación",
)
def actualizar_ubicacion(
    ubicacion_id: uuid.UUID,
    data: UbicacionUpdate,
    session: SessionDep,
    _: Annotated[
        CurrentUser, Depends(require_permission(Permission.UBICACIONES_CREAR))
    ],
):
    try:
        return service.actualizar_ubicacion(session, ubicacion_id, data)
    except service.UbicacionNoEncontrada as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ubicación no encontrada: {e}",
        ) from e
    except service.UbicacionYaExiste as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe una ubicación con el nombre: {e}",
        ) from e


@router.delete(
    "/{ubicacion_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar ubicación del catálogo",
)
def eliminar_ubicacion(
    ubicacion_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[
        CurrentUser, Depends(require_permission(Permission.UBICACIONES_CREAR))
    ],
):
    try:
        service.eliminar_ubicacion(session, ubicacion_id)
    except service.UbicacionNoEncontrada as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ubicación no encontrada: {e}",
        ) from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)
