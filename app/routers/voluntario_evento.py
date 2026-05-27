"""Router del módulo voluntario_evento (EN-02-04 / US-02-06).

Endpoints REST para que el voluntario consulte su propio historial y
resumen:

- ``GET /api/v1/voluntarios/me/historial`` (paginado con X-Total-Count).
- ``GET /api/v1/voluntarios/me/resumen`` (agregado).

Ambos exigen ``voluntarios.ver_propio`` (cualquier rol humano lo posee).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session

from app.core.database import get_session
from app.core.permissions import Permission
from app.core.security import require_permission
from app.models.voluntario_evento import TipoEventoVoluntario
from app.schemas.auth import CurrentUser
from app.schemas.voluntario_evento import (
    ResumenVoluntarioResponse,
    VoluntarioEventoResponse,
)
from app.services import voluntario_evento as service
from app.services.voluntarios import VoluntarioNoEncontrado

router = APIRouter(
    prefix="/voluntarios/me",
    tags=["historial"],
)


SessionDep = Annotated[Session, Depends(get_session)]


@router.get(
    "/historial",
    response_model=list[VoluntarioEventoResponse],
    summary="Mi historial de actividad (CU-13, US-02-06)",
)
def obtener_mi_historial(
    response: Response,
    session: SessionDep,
    user: Annotated[
        CurrentUser, Depends(require_permission(Permission.VOLUNTARIOS_VER_PROPIO))
    ],
    skip: int = Query(0, ge=0, description="Eventos a saltar (paginación)"),
    limit: int = Query(50, ge=1, le=200, description="Tamaño de página"),
    tipo: list[TipoEventoVoluntario] | None = Query(
        None,
        description=(
            "Filtrar por tipo(s) de evento. Repetir el parámetro para "
            "varios tipos: ?tipo=fichaje_entrada&tipo=fichaje_salida"
        ),
    ),
    since: datetime | None = Query(
        None, description="Solo eventos con created_at >= since"
    ),
    until: datetime | None = Query(
        None, description="Solo eventos con created_at <= until"
    ),
):
    """Lista paginada del histórico, más reciente primero."""

    try:
        items, total = service.obtener_historial_propio(
            session,
            keycloak_id=user.sub,
            skip=skip,
            limit=limit,
            tipos=tipo,
            since=since,
            until=until,
        )
    except VoluntarioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No hay un voluntario en BD vinculado al usuario actual. "
                "Pide al administrador que te dé de alta."
            ),
        ) from e

    response.headers["X-Total-Count"] = str(total)
    return items


@router.get(
    "/resumen",
    response_model=ResumenVoluntarioResponse,
    summary="Mi resumen acumulado (CU-13, US-02-06)",
)
def obtener_mi_resumen(
    session: SessionDep,
    user: Annotated[
        CurrentUser, Depends(require_permission(Permission.VOLUNTARIOS_VER_PROPIO))
    ],
):
    """Horas totales + servicios participados + último servicio."""

    try:
        return service.obtener_resumen_propio(session, keycloak_id=user.sub)
    except VoluntarioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No hay un voluntario en BD vinculado al usuario actual. "
                "Pide al administrador que te dé de alta."
            ),
        ) from e
