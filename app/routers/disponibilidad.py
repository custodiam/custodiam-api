"""Router del módulo disponibilidad (US-02-04 / CU-12).

Endpoints REST para que cada voluntario gestione su propio calendario
mensual de disponibilidad:

- ``GET  /api/v1/voluntarios/me/disponibilidad?year=YYYY&month=MM``
- ``PUT  /api/v1/voluntarios/me/disponibilidad/{fecha}``

Permisos: lectura con ``voluntarios.ver_propio``, escritura con
``voluntarios.disponibilidad_propia``. Ambos están en el frozenset
operativo base que todos los roles humanos poseen según la matriz RBAC
v0.1.0; ``admin`` (técnico puro) no los tiene por diseño.

Por simetría con los demás módulos del proyecto, el router NO importa
el repository: delega al service, que es el único responsable de
combinar reglas de negocio y persistencia.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from app.core.database import get_session
from app.core.permissions import Permission
from app.core.security import require_permission
from app.schemas.auth import CurrentUser
from app.schemas.disponibilidad import (
    DisponibilidadMesResponse,
    DisponibilidadResponse,
    DisponibilidadUpsertRequest,
)
from app.services import disponibilidad as service
from app.services.voluntarios import VoluntarioNoEncontrado

router = APIRouter(
    prefix="/voluntarios/me/disponibilidad",
    tags=["disponibilidad"],
)


SessionDep = Annotated[Session, Depends(get_session)]


@router.get(
    "",
    response_model=DisponibilidadMesResponse,
    summary="Mi disponibilidad mensual (CU-12, US-02-04)",
)
def obtener_mi_disponibilidad(
    session: SessionDep,
    user: Annotated[
        CurrentUser, Depends(require_permission(Permission.VOLUNTARIOS_VER_PROPIO))
    ],
    year: int = Query(..., ge=2000, le=2100, description="Año del calendario"),
    month: int = Query(..., ge=1, le=12, description="Mes del calendario (1-12)"),
):
    """Devuelve las filas del mes para el voluntario actual.

    Los días que no aparezcan en la lista se interpretan como "no
    disponible" en el cliente (criterio de aceptación de US-02-04).
    """

    try:
        dias = service.obtener_mi_mes(
            session, keycloak_id=user.sub, year=year, month=month
        )
    except VoluntarioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No hay un voluntario en BD vinculado al usuario actual. "
                "Pide al administrador que te dé de alta."
            ),
        ) from e
    except service.MesInvalido as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    return DisponibilidadMesResponse(year=year, month=month, dias=dias)


@router.put(
    "/{fecha}",
    response_model=DisponibilidadResponse,
    summary="Marcar mi disponibilidad de un día (CU-12, US-02-04)",
)
def marcar_mi_disponibilidad(
    fecha: date,
    body: DisponibilidadUpsertRequest,
    session: SessionDep,
    user: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.VOLUNTARIOS_DISPONIBILIDAD_PROPIA)),
    ],
):
    """Crea o actualiza idempotentemente la fila del día.

    El path captura la fecha con el parser nativo de FastAPI (ISO-8601
    ``YYYY-MM-DD``). Una fecha mal formada devuelve 422 automático.
    Una fecha anterior a hoy devuelve 422 con un mensaje de dominio.
    """

    try:
        return service.marcar_dia(
            session,
            keycloak_id=user.sub,
            fecha=fecha,
            disponible=body.disponible,
        )
    except VoluntarioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No hay un voluntario en BD vinculado al usuario actual. "
                "Pide al administrador que te dé de alta."
            ),
        ) from e
    except service.FechaPasada as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
