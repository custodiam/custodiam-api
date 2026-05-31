"""Router del módulo servicios (EN-03-02 + EN-03-03 + EN-03-04).

Endpoints REST de los CU-01..04 y CU-07. La máquina de estados se
expone con verbos en POST sobre subrutas (``/publicar``, ``/convocar``,
``/cerrar``) en lugar de PATCH al campo ``estado``, para que el
contrato del API refleje fielmente las acciones del dominio.

La autorización es declarativa con :func:`require_permission`. El
``POST /servicios`` es la única excepción: el permiso requerido depende
de ``data.tipo`` (preventivo vs emergencia), así que la comprobación se
hace dentro del handler tras parsear el body.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session

from app.core.database import get_session
from app.core.permissions import Permission
from app.core.security import get_current_user, require_permission
from app.models.servicio import EstadoServicio, TipoServicio
from app.repositories import voluntarios as voluntarios_repo
from app.schemas.auth import CurrentUser
from app.schemas.servicio import (
    ServicioCerrar,
    ServicioConvocar,
    ServicioCreate,
    ServicioResponse,
    ServicioSummary,
    ServicioUpdate,
    VoluntarioInscritoResponse,
)
from app.services import servicios as service
from app.services.fcm_admin import FcmAdminClient, get_fcm_admin
from app.services.ntfy_client import NtfyClient, get_ntfy_client

router = APIRouter(prefix="/servicios", tags=["servicios"])


SessionDep = Annotated[Session, Depends(get_session)]
FcmAdminDep = Annotated[FcmAdminClient, Depends(get_fcm_admin)]
NtfyDep = Annotated[NtfyClient, Depends(get_ntfy_client)]


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _voluntario_id_de_user(session: Session, user: CurrentUser) -> uuid.UUID:
    """Mapea el sub del JWT al id del voluntario en BD.

    Si Keycloak emite un token válido pero el voluntario no está dado
    de alta en BD aún, devuelve 404 con un mensaje claro: la sincronización
    de alta (EN-02-03) puede no haberse hecho todavía.
    """

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


def _mapear_transicion_invalida(exc: service.TransicionEstadoInvalida):
    """Construye el HTTPException 409 con un detail útil para el cliente."""

    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"Transición de estado no permitida: "
            f"{exc.actual.value} → {exc.solicitado.value}."
            + (f" {exc.motivo}" if exc.motivo else "")
        ),
    )


# ---------------------------------------------------------------------------
# Lista y detalle
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[ServicioSummary],
    summary="Listar servicios publicados (US-03-07)",
)
def listar_servicios(
    response: Response,
    session: SessionDep,
    _: Annotated[
        CurrentUser, Depends(require_permission(Permission.SERVICIOS_VER_PUBLICADOS))
    ],
    skip: int = Query(0, ge=0, description="Servicios a saltar (paginación)"),
    limit: int = Query(50, ge=1, le=200, description="Tamaño de página (máx. 200)"),
    q: str | None = Query(None, description="Búsqueda por título o ubicación"),
    estado: EstadoServicio | None = Query(
        None, description="Filtrar por estado del servicio"
    ),
    tipo: TipoServicio | None = Query(
        None, description="Filtrar por tipo de servicio"
    ),
    desde: date | None = Query(
        None, description="Filtrar servicios cuya fecha de inicio sea ≥ esta fecha"
    ),
    hasta: date | None = Query(
        None, description="Filtrar servicios cuya fecha de inicio sea ≤ esta fecha"
    ),
):
    if desde is not None and hasta is not None and desde > hasta:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El parámetro 'desde' no puede ser posterior a 'hasta'.",
        )
    items, total = service.listar(
        session,
        skip=skip,
        limit=limit,
        q=q,
        estado=estado,
        tipo=tipo,
        desde=desde,
        hasta=hasta,
    )
    response.headers["X-Total-Count"] = str(total)
    return items


@router.get(
    "/{servicio_id}",
    response_model=ServicioResponse,
    summary="Ver detalle de un servicio",
)
def obtener_servicio(
    servicio_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[
        CurrentUser, Depends(require_permission(Permission.SERVICIOS_VER_PUBLICADOS))
    ],
):
    try:
        return service.obtener(session, servicio_id)
    except service.ServicioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Servicio no encontrado: {e}",
        ) from e


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=ServicioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Alta de servicio (CU-01, US-03-01 / US-03-02)",
)
def crear_servicio(
    data: ServicioCreate,
    session: SessionDep,
    user: Annotated[CurrentUser, Depends(get_current_user)],
):
    """Crea un servicio nuevo.

    El permiso requerido depende del tipo:

    - ``emergencia`` → ``servicios.crear_emergencia``.
    - resto → ``servicios.crear_preventivo``.

    Se valida tras parsear el body para evitar declarar dos endpoints
    distintos para una misma intención del cliente (CU-01 los une).
    """

    permiso = (
        Permission.SERVICIOS_CREAR_EMERGENCIA
        if data.tipo == TipoServicio.EMERGENCIA
        else Permission.SERVICIOS_CREAR_PREVENTIVO
    )
    if not user.has_permission(permiso):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Se requiere el permiso: {permiso.value}",
        )

    return service.crear(session, data=data, creado_por_keycloak_id=user.sub)


@router.patch(
    "/{servicio_id}",
    response_model=ServicioResponse,
    summary="Modificar campos de un servicio",
)
def actualizar_servicio(
    servicio_id: uuid.UUID,
    data: ServicioUpdate,
    session: SessionDep,
    _: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.SERVICIOS_CREAR_PREVENTIVO)),
    ],
):
    """Edita campos del servicio sin tocar la máquina de estados.

    Se exige el mismo permiso que para crear preventivos por simetría:
    quien puede crear el recurso puede modificarlo. Las transiciones de
    estado siguen su flujo dedicado.
    """

    try:
        return service.actualizar(session, servicio_id, data)
    except service.ServicioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Servicio no encontrado: {e}",
        ) from e


# ---------------------------------------------------------------------------
# Transiciones de estado
# ---------------------------------------------------------------------------


@router.post(
    "/{servicio_id}/publicar",
    response_model=ServicioResponse,
    summary="Publicar servicio (CU-02, US-03-03)",
)
def publicar_servicio(
    servicio_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[
        CurrentUser, Depends(require_permission(Permission.SERVICIOS_PUBLICAR))
    ],
):
    try:
        return service.publicar(session, servicio_id)
    except service.ServicioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Servicio no encontrado: {e}",
        ) from e
    except service.TransicionEstadoInvalida as e:
        raise _mapear_transicion_invalida(e) from e


@router.post(
    "/{servicio_id}/convocar",
    response_model=ServicioResponse,
    summary="Convocar voluntarios (CU-03, US-03-04 / US-03-05 / US-03-06)",
)
def convocar_servicio(
    servicio_id: uuid.UUID,
    session: SessionDep,
    fcm_client: FcmAdminDep,
    ntfy_client: NtfyDep,
    user: Annotated[
        CurrentUser, Depends(require_permission(Permission.SERVICIOS_CONVOCAR))
    ],
    body: ServicioConvocar = ServicioConvocar(),
):
    """Convoca voluntarios al servicio.

    Si ``voluntario_ids`` está vacío, convoca a todos los activos
    (US-03-04). Si trae ids, solo esos (US-03-05). Si el servicio no
    está aún en ACTIVO, intenta la transición a ACTIVO; si la transición
    no es válida (p. ej. un preventivo en borrador), devuelve 409.

    El fan-out a Firebase Cloud Messaging y a ntfy (Epic E06) se dispara
    automáticamente tras crear las inscripciones; ambos clientes están
    inyectados aquí y delegan en :mod:`app.services.notificaciones`. Si
    los clientes están deshabilitados en config, el envío es no-op y la
    convocatoria se materializa igual en BD.
    """

    try:
        servicio, _inscripciones = service.convocar(
            session,
            servicio_id,
            voluntario_ids=body.voluntario_ids or None,
            fcm_client=fcm_client,
            ntfy_client=ntfy_client,
            actor_keycloak_id=user.sub,
        )
    except service.ServicioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Servicio no encontrado: {e}",
        ) from e
    except service.TransicionEstadoInvalida as e:
        raise _mapear_transicion_invalida(e) from e
    return servicio


@router.post(
    "/{servicio_id}/cerrar",
    response_model=ServicioResponse,
    summary="Cerrar servicio (CU-07, US-03-10)",
)
def cerrar_servicio(
    servicio_id: uuid.UUID,
    session: SessionDep,
    user: Annotated[
        CurrentUser, Depends(require_permission(Permission.SERVICIOS_CERRAR))
    ],
    body: ServicioCerrar = ServicioCerrar(),
):
    try:
        return service.cerrar(
            session,
            servicio_id,
            observaciones=body.observaciones_cierre,
            actor_keycloak_id=user.sub,
        )
    except service.ServicioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Servicio no encontrado: {e}",
        ) from e
    except service.TransicionEstadoInvalida as e:
        raise _mapear_transicion_invalida(e) from e


# ---------------------------------------------------------------------------
# Inscripciones self-service (EN-03-04 / CU-04)
# ---------------------------------------------------------------------------


@router.post(
    "/{servicio_id}/inscribirse",
    response_model=ServicioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Apuntarme a un servicio (US-03-08)",
)
def inscribirse_en_servicio(
    servicio_id: uuid.UUID,
    session: SessionDep,
    user: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.SERVICIOS_APUNTARSE_PROPIO)),
    ],
):
    voluntario_id = _voluntario_id_de_user(session, user)
    try:
        service.apuntarse_propio(
            session,
            servicio_id=servicio_id,
            voluntario_id=voluntario_id,
            actor_keycloak_id=user.sub,
        )
    except service.ServicioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Servicio no encontrado: {e}",
        ) from e
    except service.YaInscrito as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya estás inscrito en este servicio",
        ) from e
    except service.InscripcionNoPermitidaEnEsteEstado as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El servicio no admite inscripciones en su estado actual"
            ),
        ) from e

    return service.obtener(session, servicio_id)


@router.delete(
    "/{servicio_id}/inscribirse",
    response_model=ServicioResponse,
    summary="Darme de baja de un servicio (US-03-09)",
)
def desapuntarse_de_servicio(
    servicio_id: uuid.UUID,
    session: SessionDep,
    user: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.SERVICIOS_DESAPUNTARSE_PROPIO)),
    ],
):
    voluntario_id = _voluntario_id_de_user(session, user)
    try:
        service.desapuntarse_propio(
            session,
            servicio_id=servicio_id,
            voluntario_id=voluntario_id,
            actor_keycloak_id=user.sub,
        )
    except service.NoInscrito as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No estás inscrito en este servicio",
        ) from e
    except service.InscripcionNoPermitidaEnEsteEstado as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No puedes cancelar una convocatoria desde tu cuenta; "
                "pide al mando que te dé de baja"
            ),
        ) from e

    return service.obtener(session, servicio_id)


@router.get(
    "/{servicio_id}/voluntarios",
    response_model=list[VoluntarioInscritoResponse],
    summary="Listar voluntarios de un servicio (jefe+)",
)
def listar_voluntarios_servicio(
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
        pares = service.listar_voluntarios(session, servicio_id)
    except service.ServicioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Servicio no encontrado: {e}",
        ) from e

    return [
        VoluntarioInscritoResponse(
            voluntario_id=v.id,
            nombre=v.nombre,
            telefono=v.telefono,
            tipo=i.tipo,
            fecha=i.fecha,
        )
        for v, i in pares
    ]
