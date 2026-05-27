"""Router del módulo fichajes (EN-04-02 + EN-04-03).

Dos routers conviven en este archivo:

- ``router`` — sub-recurso de servicio: ``/servicios/{id}/fichaje/...``.
  Aquí viven los endpoints "actuar sobre el fichaje de mi voluntario
  en este servicio" (entrada/salida) y la lista por servicio para los
  mandos (US-04-04).
- ``self_router`` — endpoints de "mis fichajes": ``/fichajes/...``.
  Sirven el historial propio (US-04-03) sin acoplar la URL al servicio.

Ambos se montan desde ``app/main.py`` con el mismo prefix de versión.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.core.database import get_session
from app.core.permissions import Permission
from app.core.security import require_permission
from app.repositories import voluntarios as voluntarios_repo
from app.schemas.auth import CurrentUser
from app.schemas.fichaje import (
    FichajeEnServicioResponse,
    FichajeResponse,
    HorasAcumuladasResponse,
)
from app.services import fichajes as service
from app.services.servicios import ServicioNoEncontrado

router = APIRouter(
    prefix="/servicios/{servicio_id}/fichaje", tags=["fichaje"]
)
self_router = APIRouter(prefix="/fichajes", tags=["fichaje"])


SessionDep = Annotated[Session, Depends(get_session)]


def _voluntario_id_de_user(session: Session, user: CurrentUser) -> uuid.UUID:
    """Mapea el sub del JWT al id del voluntario en BD."""

    v = voluntarios_repo.get_by_keycloak_id(session, user.sub)
    if v is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Tu cuenta de Keycloak no está vinculada a un voluntario en BD. "
                "Pide al administrador que te dé de alta."
            ),
        )
    return v.id


# ---------------------------------------------------------------------------
# Endpoints sub-recurso del servicio
# ---------------------------------------------------------------------------


@router.post(
    "/entrada",
    response_model=FichajeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Fichar mi entrada al servicio (CU-05, US-04-01)",
)
def fichar_entrada(
    servicio_id: uuid.UUID,
    session: SessionDep,
    user: Annotated[
        CurrentUser, Depends(require_permission(Permission.FICHAJE_FICHAR_PROPIO))
    ],
):
    voluntario_id = _voluntario_id_de_user(session, user)
    try:
        fichaje = service.fichar_entrada(
            session,
            servicio_id=servicio_id,
            voluntario_id=voluntario_id,
        )
    except ServicioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Servicio no encontrado: {e}",
        ) from e
    except service.ServicioNoActivo as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El servicio no admite fichajes: {e}",
        ) from e
    except service.VoluntarioNoInscritoNiConvocado as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    except service.YaFichado as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya tienes una entrada fichada en este servicio",
        ) from e

    return FichajeResponse(
        id=fichaje.id,
        servicio_id=fichaje.servicio_id,
        voluntario_id=fichaje.voluntario_id,
        hora_entrada=fichaje.hora_entrada,
        hora_salida=fichaje.hora_salida,
        automatico=fichaje.automatico,
        duracion_segundos=fichaje.duracion_segundos,
    )


@router.post(
    "/salida",
    response_model=FichajeResponse,
    summary="Fichar mi salida del servicio (CU-06, US-04-02)",
)
def fichar_salida(
    servicio_id: uuid.UUID,
    session: SessionDep,
    user: Annotated[
        CurrentUser, Depends(require_permission(Permission.FICHAJE_FICHAR_PROPIO))
    ],
):
    voluntario_id = _voluntario_id_de_user(session, user)
    try:
        fichaje = service.fichar_salida(
            session,
            servicio_id=servicio_id,
            voluntario_id=voluntario_id,
        )
    except service.SinFichajeAbierto as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e

    return FichajeResponse(
        id=fichaje.id,
        servicio_id=fichaje.servicio_id,
        voluntario_id=fichaje.voluntario_id,
        hora_entrada=fichaje.hora_entrada,
        hora_salida=fichaje.hora_salida,
        automatico=fichaje.automatico,
        duracion_segundos=fichaje.duracion_segundos,
    )


@router.get(
    "",
    response_model=list[FichajeEnServicioResponse],
    summary="Listar voluntarios fichados en un servicio (jefe+, US-04-04)",
)
def listar_fichajes_servicio(
    servicio_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[
        CurrentUser,
        Depends(
            require_permission(Permission.FICHAJE_VER_VOLUNTARIOS_EN_SERVICIO)
        ),
    ],
):
    try:
        pares = service.listar_por_servicio(session, servicio_id)
    except ServicioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Servicio no encontrado: {e}",
        ) from e

    return [
        FichajeEnServicioResponse(
            fichaje_id=f.id,
            voluntario_id=v.id,
            nombre=v.nombre,
            hora_entrada=f.hora_entrada,
            hora_salida=f.hora_salida,
            automatico=f.automatico,
            duracion_segundos=f.duracion_segundos,
        )
        for v, f in pares
    ]


# ---------------------------------------------------------------------------
# Endpoints "mis fichajes"
# ---------------------------------------------------------------------------


@self_router.get(
    "/me",
    response_model=list[FichajeResponse],
    summary="Listar mis fichajes (US-04-03)",
)
def listar_mis_fichajes(
    session: SessionDep,
    user: Annotated[
        CurrentUser, Depends(require_permission(Permission.FICHAJE_VER_PROPIO))
    ],
):
    voluntario_id = _voluntario_id_de_user(session, user)
    fichajes = service.listar_por_voluntario(session, voluntario_id)
    return [
        FichajeResponse(
            id=f.id,
            servicio_id=f.servicio_id,
            voluntario_id=f.voluntario_id,
            hora_entrada=f.hora_entrada,
            hora_salida=f.hora_salida,
            automatico=f.automatico,
            duracion_segundos=f.duracion_segundos,
        )
        for f in fichajes
    ]


@self_router.get(
    "/me/horas",
    response_model=HorasAcumuladasResponse,
    summary="Resumen de mis horas acumuladas (EN-04-03)",
)
def obtener_mis_horas(
    session: SessionDep,
    user: Annotated[
        CurrentUser, Depends(require_permission(Permission.FICHAJE_VER_PROPIO))
    ],
):
    voluntario_id = _voluntario_id_de_user(session, user)
    total_seg, n_cerrados, n_abiertos = service.horas_acumuladas(
        session, voluntario_id
    )
    return HorasAcumuladasResponse(
        voluntario_id=voluntario_id,
        total_segundos=total_seg,
        total_horas=round(total_seg / 3600, 2),
        fichajes_cerrados=n_cerrados,
        fichajes_abiertos=n_abiertos,
    )
