"""Router del módulo dispositivos (Epic E06).

Endpoints REST para que cada voluntario gestione sus propios tokens FCM:

- ``POST   /dispositivos`` — registrar/refrescar mi token (US-06-04).
- ``GET    /dispositivos/me`` — listar mis dispositivos activos.
- ``DELETE /dispositivos/{id}`` — auto-baja de uno de mis dispositivos.

Las tres rutas exigen el permiso ``notificaciones.registrar_token``,
del que todos los roles humanos disponen según la matriz RBAC.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import Session

from app.core.database import get_session
from app.core.permissions import Permission
from app.core.security import require_permission
from app.repositories import voluntarios as voluntarios_repo
from app.schemas.auth import CurrentUser
from app.schemas.dispositivo import DispositivoRegistrar, DispositivoResponse
from app.services import dispositivos as service

router = APIRouter(prefix="/dispositivos", tags=["dispositivos"])


SessionDep = Annotated[Session, Depends(get_session)]


def _voluntario_id_de_user(session: Session, user: CurrentUser) -> uuid.UUID:
    """Mapea el ``sub`` del JWT al ``id`` del voluntario en BD.

    Si Keycloak emite un token válido pero el voluntario aún no está en
    BD (la sincronización de alta EN-02-03 puede no haber corrido), se
    devuelve 404 con un mensaje accionable. Mismo patrón que el helper
    homónimo de ``routers/servicios.py``; se duplica deliberadamente
    para no introducir un módulo de helpers compartidos antes de tener
    un tercer consumidor que lo justifique.
    """

    v = voluntarios_repo.get_by_keycloak_id(session, user.sub)
    if v is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Tu cuenta de Keycloak no está vinculada a un voluntario "
                "en BD. Pide al administrador que te dé de alta."
            ),
        )
    return v.id


@router.post(
    "",
    response_model=DispositivoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar mi token FCM (US-06-04)",
)
def registrar_dispositivo(
    data: DispositivoRegistrar,
    session: SessionDep,
    user: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.NOTIFICACIONES_REGISTRAR_TOKEN)),
    ],
):
    """Registra (o refresca) el token FCM del voluntario actual.

    El endpoint es idempotente: enviar el mismo ``fcm_token`` no crea
    filas duplicadas, solo reactiva el flag ``activo`` y, si el token
    estaba vinculado a otro voluntario, lo reasigna al actual.
    """

    voluntario_id = _voluntario_id_de_user(session, user)
    return service.registrar(
        session,
        voluntario_id=voluntario_id,
        fcm_token=data.fcm_token,
        plataforma=data.plataforma,
    )


@router.get(
    "/me",
    response_model=list[DispositivoResponse],
    summary="Listar mis dispositivos activos",
)
def listar_mis_dispositivos(
    session: SessionDep,
    user: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.NOTIFICACIONES_REGISTRAR_TOKEN)),
    ],
):
    voluntario_id = _voluntario_id_de_user(session, user)
    return service.listar_propios(session, voluntario_id)


@router.delete(
    "/{dispositivo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Dar de baja un dispositivo propio",
)
def dar_baja_dispositivo(
    dispositivo_id: uuid.UUID,
    session: SessionDep,
    user: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.NOTIFICACIONES_REGISTRAR_TOKEN)),
    ],
):
    """Soft delete del dispositivo. Solo el propietario puede operarlo.

    Si el id existe pero pertenece a otro voluntario, devuelve 403 —
    no 404 — para que el cliente pueda distinguir el caso "ese
    dispositivo no es tuyo" del caso "ese dispositivo ya no existe".
    """

    voluntario_id = _voluntario_id_de_user(session, user)
    try:
        service.dar_baja_propio(
            session,
            dispositivo_id=dispositivo_id,
            voluntario_id_actual=voluntario_id,
        )
    except service.DispositivoNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispositivo no encontrado: {e}",
        ) from e
    except service.DispositivoDeOtroVoluntario as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El dispositivo pertenece a otro voluntario",
        ) from e

    return Response(status_code=status.HTTP_204_NO_CONTENT)
