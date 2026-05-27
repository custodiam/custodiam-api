"""Router del módulo voluntarios (EN-02-02).

Endpoints REST del CU-10 (alta), CU-11 (modificación admin y self),
CU-13 (consulta del propio perfil) y US-02-09 (lista). El soft delete
y la anonimización RGPD viven en dos endpoints diferenciados.

La autorización es declarativa con :func:`require_permission`: el mapa
rol→permisos vive en :mod:`app.core.permissions`. Las reglas de
propiedad (p. ej. "solo me edito a mí mismo") se enforzan en el
servicio comparando `keycloak_id` contra el `sub` del JWT.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session

from app.core.database import get_session
from app.core.permissions import Permission
from app.core.security import get_current_user, require_permission
from app.models.voluntario import EstadoVoluntario
from app.schemas.auth import CurrentUser
from app.schemas.voluntario import (
    AsignarRolRequest,
    VoluntarioCreate,
    VoluntarioResponse,
    VoluntarioRolResponse,
    VoluntarioSummary,
    VoluntarioUpdateAdmin,
    VoluntarioUpdateSelf,
)
from app.services import voluntarios as service
from app.services.keycloak_admin import (
    KeycloakAdminClient,
    KeycloakAdminError,
    get_keycloak_admin,
)

router = APIRouter(prefix="/voluntarios", tags=["voluntarios"])


SessionDep = Annotated[Session, Depends(get_session)]
KeycloakAdminDep = Annotated[KeycloakAdminClient, Depends(get_keycloak_admin)]


# ---------------------------------------------------------------------------
# Lista
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[VoluntarioSummary],
    summary="Listar voluntarios (US-02-09)",
)
def listar_voluntarios(
    response: Response,
    session: SessionDep,
    _: Annotated[
        CurrentUser, Depends(require_permission(Permission.VOLUNTARIOS_LISTAR))
    ],
    skip: int = Query(0, ge=0, description="Voluntarios a saltar (paginación)"),
    limit: int = Query(50, ge=1, le=200, description="Tamaño de página (máx. 200)"),
    q: str | None = Query(None, description="Búsqueda por nombre, email o DNI"),
    estado: EstadoVoluntario | None = Query(
        None, description="Filtrar por estado (activo, baja, suspendido)"
    ),
    rol_id: uuid.UUID | None = Query(
        None, description="Solo voluntarios con este rol activo"
    ),
):
    """Lista paginada de voluntarios con filtros opcionales.

    El total se devuelve en el header ``X-Total-Count`` para que el
    cliente pueda paginar sin emitir un HEAD adicional.
    """

    items, total = service.listar(
        session,
        skip=skip,
        limit=limit,
        q=q,
        estado=estado,
        rol_id=rol_id,
    )
    response.headers["X-Total-Count"] = str(total)
    return items


# ---------------------------------------------------------------------------
# Self-service (rutas con `/me` antes de `/{id}`)
# ---------------------------------------------------------------------------


@router.get(
    "/me",
    response_model=VoluntarioResponse,
    summary="Consultar mi perfil (CU-13)",
)
def obtener_mi_perfil(
    session: SessionDep,
    user: Annotated[
        CurrentUser, Depends(require_permission(Permission.VOLUNTARIOS_VER_PROPIO))
    ],
):
    try:
        return service.obtener_propio(session, user.sub)
    except service.VoluntarioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No hay un voluntario en BD vinculado al usuario actual. "
                "Pide al administrador que te dé de alta."
            ),
        ) from e


@router.patch(
    "/me",
    response_model=VoluntarioResponse,
    summary="Editar mis datos de contacto (CU-11 A)",
)
def actualizar_mi_perfil(
    data: VoluntarioUpdateSelf,
    session: SessionDep,
    user: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.VOLUNTARIOS_EDITAR_PROPIO)),
    ],
):
    try:
        service.actualizar_propio(session, user.sub, data)
    except service.VoluntarioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay un voluntario en BD vinculado al usuario actual.",
        ) from e
    except service.EmailDuplicado as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email ya registrado: {e}",
        ) from e

    return service.obtener_propio(session, user.sub)


# ---------------------------------------------------------------------------
# CRUD admin
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=VoluntarioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Alta de voluntario (CU-10, US-02-01)",
)
def crear_voluntario(
    data: VoluntarioCreate,
    session: SessionDep,
    kc_admin: KeycloakAdminDep,
    _: Annotated[
        CurrentUser, Depends(require_permission(Permission.VOLUNTARIOS_CREAR))
    ],
):
    """Crea un voluntario en BD y, si la Admin API está configurada,
    también en Keycloak.

    Orden de operaciones (EN-02-03):

    1. Validar reglas de dominio y unicidad (DNI, email) en BD.
    2. Crear el usuario en Keycloak. Si falla, abortamos sin tocar BD
       para evitar voluntarios huérfanos sin cuenta. El cliente está
       diseñado para devolver ``None`` en modo deshabilitado (sin
       credenciales de admin), en cuyo caso seguimos sin sincronizar.
    3. Crear el voluntario en BD con el `keycloak_id` recién obtenido.
    """

    # 1. Validación previa (sin escribir).
    if data.dni and _exists_in_db_dni(session, data.dni):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"DNI ya registrado: {data.dni}",
        )
    if data.email and _exists_in_db_email(session, data.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email ya registrado: {data.email}",
        )

    # 2. Sincronización con Keycloak (si está habilitada).
    username = _username_para_keycloak(data)
    keycloak_id: str | None = None
    try:
        keycloak_id = kc_admin.crear_usuario(
            username=username,
            email=data.email,
            given_name=data.nombre.split(" ", 1)[0],
            family_name=" ".join(data.nombre.split(" ", 1)[1:]) or data.nombre,
        )
    except KeycloakAdminError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Sincronización con Keycloak fallida: {e}",
        ) from e

    # 3. Persistencia en BD.
    try:
        v = service.crear(session, data=data, keycloak_id=keycloak_id)
    except service.DniDuplicado as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"DNI ya registrado: {e}",
        ) from e
    except service.EmailDuplicado as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email ya registrado: {e}",
        ) from e

    # Recargamos con relaciones para que el response_model encuentre las
    # listas vacías y no `MissingGreenlet` al lazy-loadear fuera de la
    # request. En POST son siempre listas vacías porque el voluntario
    # acaba de crearse, pero la serialización las necesita.
    return service.obtener(session, v.id)


def _exists_in_db_dni(session: Session, dni: str) -> bool:
    from app.repositories import voluntarios as repo

    return repo.exists_with_dni(session, dni)


def _exists_in_db_email(session: Session, email: str) -> bool:
    from app.repositories import voluntarios as repo

    return repo.exists_with_email(session, email)


def _username_para_keycloak(data: VoluntarioCreate) -> str:
    """Construye un `username` razonable para Keycloak.

    Preferimos el DNI si está, porque es estable y único; si no, el
    email; si no, una transliteración del nombre (último recurso, que
    el admin debería corregir manualmente).
    """

    if data.dni:
        return data.dni.lower()
    if data.email:
        return data.email
    # Heurística mínima — el admin debería normalizar después si quiere.
    return data.nombre.lower().replace(" ", ".")


@router.get(
    "/{voluntario_id}",
    response_model=VoluntarioResponse,
    summary="Ver ficha completa de un voluntario",
)
def obtener_voluntario(
    voluntario_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[
        CurrentUser, Depends(require_permission(Permission.VOLUNTARIOS_VER_FICHA))
    ],
):
    try:
        return service.obtener(session, voluntario_id)
    except service.VoluntarioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Voluntario no encontrado: {e}",
        ) from e


@router.patch(
    "/{voluntario_id}",
    response_model=VoluntarioResponse,
    summary="Modificar voluntario (CU-11 B, US-02-02)",
)
def actualizar_voluntario(
    voluntario_id: uuid.UUID,
    data: VoluntarioUpdateAdmin,
    session: SessionDep,
    _: Annotated[
        CurrentUser, Depends(require_permission(Permission.VOLUNTARIOS_EDITAR))
    ],
):
    try:
        service.actualizar_admin(session, voluntario_id, data)
    except service.VoluntarioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Voluntario no encontrado: {e}",
        ) from e
    except service.DniDuplicado as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"DNI ya registrado: {e}",
        ) from e
    except service.EmailDuplicado as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email ya registrado: {e}",
        ) from e

    return service.obtener(session, voluntario_id)


@router.delete(
    "/{voluntario_id}",
    response_model=VoluntarioResponse,
    summary="Dar de baja a un voluntario (soft delete)",
)
def dar_baja_voluntario(
    voluntario_id: uuid.UUID,
    session: SessionDep,
    kc_admin: KeycloakAdminDep,
    _: Annotated[
        CurrentUser, Depends(require_permission(Permission.VOLUNTARIOS_DAR_BAJA))
    ],
):
    """Soft delete operativo.

    Mantiene el histórico de actividad (horas, servicios, equipamiento)
    y el `keycloak_id` para poder reactivar. Para borrar PII de verdad,
    usar el endpoint específico de anonimización (Art. 17 RGPD).

    Si la Admin API de Keycloak está configurada, también desactiva la
    cuenta del usuario en Keycloak (`enabled=false`). La cuenta no se
    borra: reactivar al voluntario más adelante solo requiere volver a
    poner `enabled=true`.
    """

    try:
        voluntario = service.dar_baja(session, voluntario_id)
    except service.VoluntarioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Voluntario no encontrado: {e}",
        ) from e

    if voluntario.keycloak_id:
        try:
            kc_admin.desactivar_usuario(voluntario.keycloak_id)
        except KeycloakAdminError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "Voluntario marcado de baja en BD pero la "
                    f"desactivación en Keycloak falló: {e}"
                ),
            ) from e

    return service.obtener(session, voluntario_id)


@router.post(
    "/{voluntario_id}/anonimizar",
    response_model=VoluntarioResponse,
    summary="Anonimizar voluntario (Art. 17 RGPD)",
)
def anonimizar_voluntario(
    voluntario_id: uuid.UUID,
    session: SessionDep,
    kc_admin: KeycloakAdminDep,
    _: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.SISTEMA_EXPORTAR_RGPD)),
    ],
):
    """Anonimización irreversible de los datos personales.

    Permiso `sistema.exportar_rgpd` restringido a jefe_agrupacion,
    coordinador, secretario y admin. Se invoca solo a petición expresa
    del titular del dato (formulario de ejercicio de derechos ARCO+).

    Si la Admin API de Keycloak está configurada, también desactiva la
    cuenta en Keycloak antes de borrar el `keycloak_id` de la fila en BD.
    """

    # Capturamos el `keycloak_id` ANTES de anonimizar porque el service
    # lo pone a NULL en BD.
    try:
        actual = service.obtener(session, voluntario_id)
    except service.VoluntarioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Voluntario no encontrado: {e}",
        ) from e
    keycloak_id_antes = actual.keycloak_id

    service.anonimizar(session, voluntario_id)

    if keycloak_id_antes:
        try:
            kc_admin.desactivar_usuario(keycloak_id_antes)
        except KeycloakAdminError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "Voluntario anonimizado en BD pero la desactivación "
                    f"en Keycloak falló: {e}"
                ),
            ) from e

    return service.obtener(session, voluntario_id)


# ---------------------------------------------------------------------------
# Asignación de roles (EN-02-05)
# ---------------------------------------------------------------------------


@router.post(
    "/{voluntario_id}/roles",
    response_model=VoluntarioRolResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Asignar un rol a un voluntario (EN-02-05)",
)
def asignar_rol_a_voluntario(
    voluntario_id: uuid.UUID,
    data: AsignarRolRequest,
    session: SessionDep,
    kc_admin: KeycloakAdminDep,
    _: Annotated[
        CurrentUser, Depends(require_permission(Permission.VOLUNTARIOS_EDITAR))
    ],
):
    """Asigna un rol al voluntario.

    Orden de operaciones (mismo patrón que ``crear_voluntario`` de
    EN-02-03):

    1. Validar voluntario y rol en BD; rechazar si ya hay una
       asignación activa (idempotencia explícita: 409 en lugar de un
       no-op silencioso).
    2. Sincronizar con Keycloak. Si la Admin API está deshabilitada
       (modo dev / tests), se omite sin error. Si la llamada falla,
       devolvemos 502 sin tocar BD para evitar asignaciones huérfanas.
    3. Persistir la fila en ``voluntario_roles``.

    Si el voluntario no tiene ``keycloak_id`` set en BD, se asigna solo
    en BD: no hay nada que sincronizar.
    """

    # 1. Validar antes de tocar nada (incluye el chequeo de duplicado).
    try:
        # `asignar_rol` valida pero también crea — para mantener el
        # patrón "KC antes de BD" lo dividimos: aquí solo validamos.
        # Reutilizamos el repo directo para no duplicar lógica.
        from app.repositories import voluntarios as repo

        voluntario = repo.get(session, voluntario_id)
        if voluntario is None:
            raise service.VoluntarioNoEncontrado(str(voluntario_id))
        rol = repo.get_rol(session, data.rol_id)
        if rol is None:
            raise service.RolNoEncontrado(str(data.rol_id))
        if repo.get_asignacion_activa(
            session, voluntario_id=voluntario_id, rol_id=data.rol_id
        ) is not None:
            raise service.RolYaAsignado(rol.nombre)
    except service.VoluntarioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Voluntario no encontrado: {e}",
        ) from e
    except service.RolNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rol no encontrado: {e}",
        ) from e
    except service.RolYaAsignado as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"El voluntario ya tiene asignado el rol {e}; "
                "para reasignar, quítalo primero."
            ),
        ) from e

    # 2. Sincronización con Keycloak (si está habilitada y el voluntario
    #    está en KC).
    if voluntario.keycloak_id:
        try:
            kc_admin.asignar_rol_realm(voluntario.keycloak_id, rol.nombre)
        except KeycloakAdminError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Sincronización con Keycloak fallida: {e}",
            ) from e

    # 3. Persistencia en BD.
    asignacion, _rol = service.asignar_rol(
        session, voluntario_id=voluntario_id, rol_id=data.rol_id
    )

    return VoluntarioRolResponse(
        id=asignacion.id,
        voluntario_id=asignacion.voluntario_id,
        rol_id=asignacion.rol_id,
        rol_nombre=rol.nombre,
        fecha_desde=asignacion.fecha_desde,
        fecha_hasta=asignacion.fecha_hasta,
    )


@router.delete(
    "/{voluntario_id}/roles/{rol_id}",
    response_model=VoluntarioRolResponse,
    summary="Quitar un rol a un voluntario (EN-02-05)",
)
def quitar_rol_a_voluntario(
    voluntario_id: uuid.UUID,
    rol_id: uuid.UUID,
    session: SessionDep,
    kc_admin: KeycloakAdminDep,
    _: Annotated[
        CurrentUser, Depends(require_permission(Permission.VOLUNTARIOS_EDITAR))
    ],
):
    """Quita un rol al voluntario (soft delete con histórico).

    Mismo orden que la asignación:

    1. Validar voluntario, rol y asignación activa.
    2. Sincronizar con Keycloak (si aplica).
    3. Marcar ``fecha_hasta=today`` en ``voluntario_roles``.
    """

    try:
        from app.repositories import voluntarios as repo

        voluntario = repo.get(session, voluntario_id)
        if voluntario is None:
            raise service.VoluntarioNoEncontrado(str(voluntario_id))
        rol = repo.get_rol(session, rol_id)
        if rol is None:
            raise service.RolNoEncontrado(str(rol_id))
        if (
            repo.get_asignacion_activa(
                session, voluntario_id=voluntario_id, rol_id=rol_id
            )
            is None
        ):
            raise service.RolNoAsignado(rol.nombre)
    except service.VoluntarioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Voluntario no encontrado: {e}",
        ) from e
    except service.RolNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rol no encontrado: {e}",
        ) from e
    except service.RolNoAsignado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"El voluntario no tiene asignado el rol {e}",
        ) from e

    if voluntario.keycloak_id:
        try:
            kc_admin.quitar_rol_realm(voluntario.keycloak_id, rol.nombre)
        except KeycloakAdminError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Sincronización con Keycloak fallida: {e}",
            ) from e

    asignacion, _rol = service.quitar_rol(
        session, voluntario_id=voluntario_id, rol_id=rol_id
    )

    return VoluntarioRolResponse(
        id=asignacion.id,
        voluntario_id=asignacion.voluntario_id,
        rol_id=asignacion.rol_id,
        rol_nombre=rol.nombre,
        fecha_desde=asignacion.fecha_desde,
        fecha_hasta=asignacion.fecha_hasta,
    )


# Re-export para que main.py lo importe directamente.
__all__ = ["router", "get_current_user"]
