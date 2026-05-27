"""Router del módulo inventario (EN-05-02 + EN-05-03 + EN-05-04).

Dos routers conviven en este archivo (mismo patrón que `fichajes.py`):

- ``router`` con prefix ``/inventario`` — recursos directos
  ``/inventario/material`` y ``/inventario/vehiculos`` + acciones
  (incidencia, reparar, asignar a voluntario, devolver).
- ``servicio_router`` con prefix ``/servicios/{servicio_id}/inventario``
  — acciones que cuelgan del servicio: asignar material/vehículo al
  servicio (CU-22). Esto refleja que el actor mental "asignar a
  servicio" arranca desde la pestaña del servicio, no desde la del
  inventario.

Ambos se montan desde ``app/main.py`` con el mismo prefix de versión.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session

from app.core.database import get_session
from app.core.permissions import Permission
from app.core.security import get_current_user, require_permission
from app.models.asignacion_material import TipoAsignacion
from app.models.material import EstadoInventario, TipoMaterial
from app.models.vehiculo import TipoVehiculo
from app.schemas.auth import CurrentUser
from app.schemas.inventario import (
    AsignacionMaterialResponse,
    AsignacionVehiculoResponse,
    AsignarMaterialServicioRequest,
    AsignarMaterialVoluntarioRequest,
    AsignarVehiculoServicioRequest,
    DevolverMaterialRequest,
    IncidenciaMaterialRequest,
    IncidenciaVehiculoRequest,
    MaterialCreate,
    MaterialResponse,
    MaterialSummary,
    MaterialUpdate,
    VehiculoCreate,
    VehiculoResponse,
    VehiculoSummary,
    VehiculoUpdate,
)
from app.services import inventario as service

router = APIRouter(prefix="/inventario", tags=["inventario"])
servicio_router = APIRouter(
    prefix="/servicios/{servicio_id}/inventario", tags=["inventario"]
)

SessionDep = Annotated[Session, Depends(get_session)]


def _asignacion_to_response(asignacion) -> AsignacionMaterialResponse:
    return AsignacionMaterialResponse(
        id=asignacion.id,
        material_id=asignacion.material_id,
        voluntario_id=asignacion.voluntario_id,
        servicio_id=asignacion.servicio_id,
        tipo=asignacion.tipo,
        cantidad=asignacion.cantidad,
        fecha_asignacion=asignacion.fecha_asignacion,
        fecha_devolucion=asignacion.fecha_devolucion,
        observaciones_devolucion=asignacion.observaciones_devolucion,
        activa=asignacion.activa,
    )


def _asignacion_vehiculo_to_response(asignacion) -> AsignacionVehiculoResponse:
    return AsignacionVehiculoResponse(
        id=asignacion.id,
        vehiculo_id=asignacion.vehiculo_id,
        servicio_id=asignacion.servicio_id,
        fecha_asignacion=asignacion.fecha_asignacion,
        fecha_devolucion=asignacion.fecha_devolucion,
        observaciones=asignacion.observaciones,
        activa=asignacion.activa,
    )


# ---------------------------------------------------------------------------
# Material — CRUD básico
# ---------------------------------------------------------------------------


@router.get(
    "/material",
    response_model=list[MaterialSummary],
    summary="Listar material del inventario (US-05-10)",
)
def listar_material(
    response: Response,
    session: SessionDep,
    _: Annotated[
        CurrentUser, Depends(require_permission(Permission.INVENTARIO_VER))
    ],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    q: str | None = Query(None, description="Búsqueda por nombre o código"),
    estado: EstadoInventario | None = None,
    tipo: TipoMaterial | None = None,
    categoria: str | None = None,
):
    items, total = service.listar_materiales(
        session,
        skip=skip,
        limit=limit,
        q=q,
        estado=estado,
        tipo=tipo,
        categoria=categoria,
    )
    response.headers["X-Total-Count"] = str(total)
    return items


@router.get(
    "/material/{material_id}",
    response_model=MaterialResponse,
    summary="Ver ficha de un material",
)
def obtener_material(
    material_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[
        CurrentUser, Depends(require_permission(Permission.INVENTARIO_VER))
    ],
):
    try:
        return service.obtener_material(session, material_id)
    except service.MaterialNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Material no encontrado: {e}",
        ) from e


@router.post(
    "/material",
    response_model=MaterialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar material (CU-20, US-05-01)",
)
def crear_material(
    data: MaterialCreate,
    session: SessionDep,
    _: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.INVENTARIO_REGISTRAR_MATERIAL)),
    ],
):
    return service.crear_material(session, data)


@router.patch(
    "/material/{material_id}",
    response_model=MaterialResponse,
    summary="Modificar material",
)
def actualizar_material(
    material_id: uuid.UUID,
    data: MaterialUpdate,
    session: SessionDep,
    _: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.INVENTARIO_REGISTRAR_MATERIAL)),
    ],
):
    try:
        return service.actualizar_material(session, material_id, data)
    except service.MaterialNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Material no encontrado: {e}",
        ) from e


# ---------------------------------------------------------------------------
# Material — Incidencias y reparación (CU-24)
# ---------------------------------------------------------------------------


@router.post(
    "/material/{material_id}/incidencia",
    response_model=MaterialResponse,
    summary="Reportar avería o pérdida (CU-24, US-05-08 / US-05-09)",
)
def reportar_incidencia_material(
    material_id: uuid.UUID,
    body: IncidenciaMaterialRequest,
    session: SessionDep,
    _: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.INVENTARIO_REPORTAR_INCIDENCIA)),
    ],
):
    try:
        return service.reportar_incidencia_material(
            session,
            material_id,
            nuevo_estado=body.tipo,
            descripcion=body.descripcion,
        )
    except service.MaterialNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Material no encontrado: {e}",
        ) from e
    except service.EstadoIncidenciaInvalido as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    except service.MaterialEnEstadoFinal as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e


@router.post(
    "/material/{material_id}/reparar",
    response_model=MaterialResponse,
    summary="Rehabilitar material averiado (CU-24 nota)",
)
def reparar_material(
    material_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.INVENTARIO_REGISTRAR_MATERIAL)),
    ],
):
    try:
        return service.reparar_material(session, material_id)
    except service.MaterialNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Material no encontrado: {e}",
        ) from e
    except service.MaterialEnEstadoFinal as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e


# ---------------------------------------------------------------------------
# Material — Asignación a voluntario y devolución
# ---------------------------------------------------------------------------


@router.post(
    "/material/{material_id}/asignar",
    response_model=AsignacionMaterialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Asignar material a voluntario (CU-21, US-05-03 / US-05-04)",
)
def asignar_material_a_voluntario(
    material_id: uuid.UUID,
    body: AsignarMaterialVoluntarioRequest,
    session: SessionDep,
    user: Annotated[CurrentUser, Depends(get_current_user)],
):
    """Asigna material a un voluntario en modo PERSONAL o PRESTAMO.

    El permiso requerido depende de ``body.tipo``:

    - ``PERSONAL`` → ``inventario.asignar_equipamiento_personal``.
    - ``PRESTAMO`` → ``inventario.prestar_temporal``.

    Se valida tras parsear el body por consistencia con el ``POST
    /servicios`` de EN-03 (permiso dinámico según body).
    """

    permiso = (
        Permission.INVENTARIO_ASIGNAR_EQUIPAMIENTO_PERSONAL
        if body.tipo == TipoAsignacion.PERSONAL
        else Permission.INVENTARIO_PRESTAR_TEMPORAL
    )
    if not user.has_permission(permiso):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Se requiere el permiso: {permiso.value}",
        )

    try:
        asignacion = service.asignar_material_a_voluntario(
            session,
            material_id=material_id,
            voluntario_id=body.voluntario_id,
            tipo=body.tipo,
            cantidad=body.cantidad,
        )
    except service.MaterialNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Material no encontrado: {e}",
        ) from e
    except service.MaterialNoOperativo as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    except service.TipoAsignacionNoCompatible as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    except service.MaterialYaAsignadoAVoluntario as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    except service.CantidadInsuficiente as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e

    return _asignacion_to_response(asignacion)


@router.post(
    "/material/{material_id}/devolver",
    response_model=AsignacionMaterialResponse,
    summary="Devolver material asignado a voluntario (CU-23, US-05-05)",
)
def devolver_material(
    material_id: uuid.UUID,
    body: DevolverMaterialRequest,
    session: SessionDep,
    _: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.INVENTARIO_REGISTRAR_DEVOLUCION)),
    ],
):
    try:
        asignacion = service.devolver_material(
            session,
            material_id=material_id,
            voluntario_id=body.voluntario_id,
            observaciones=body.observaciones,
        )
    except service.MaterialNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Material no encontrado: {e}",
        ) from e
    except service.AsignacionNoEncontrada as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    return _asignacion_to_response(asignacion)


# ---------------------------------------------------------------------------
# Vehículo — CRUD básico
# ---------------------------------------------------------------------------


@router.get(
    "/vehiculos",
    response_model=list[VehiculoSummary],
    summary="Listar vehículos (US-05-10)",
)
def listar_vehiculos(
    response: Response,
    session: SessionDep,
    _: Annotated[
        CurrentUser, Depends(require_permission(Permission.INVENTARIO_VER))
    ],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    q: str | None = None,
    estado: EstadoInventario | None = None,
    tipo: TipoVehiculo | None = None,
):
    items, total = service.listar_vehiculos(
        session, skip=skip, limit=limit, q=q, estado=estado, tipo=tipo
    )
    response.headers["X-Total-Count"] = str(total)
    return items


@router.get(
    "/vehiculos/{vehiculo_id}",
    response_model=VehiculoResponse,
    summary="Ver ficha de un vehículo",
)
def obtener_vehiculo(
    vehiculo_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[
        CurrentUser, Depends(require_permission(Permission.INVENTARIO_VER))
    ],
):
    try:
        return service.obtener_vehiculo(session, vehiculo_id)
    except service.VehiculoNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehículo no encontrado: {e}",
        ) from e


@router.post(
    "/vehiculos",
    response_model=VehiculoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar vehículo (CU-20 flujo A, US-05-02)",
)
def crear_vehiculo(
    data: VehiculoCreate,
    session: SessionDep,
    _: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.INVENTARIO_REGISTRAR_VEHICULO)),
    ],
):
    return service.crear_vehiculo(session, data)


@router.patch(
    "/vehiculos/{vehiculo_id}",
    response_model=VehiculoResponse,
    summary="Modificar vehículo",
)
def actualizar_vehiculo(
    vehiculo_id: uuid.UUID,
    data: VehiculoUpdate,
    session: SessionDep,
    _: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.INVENTARIO_REGISTRAR_VEHICULO)),
    ],
):
    try:
        return service.actualizar_vehiculo(session, vehiculo_id, data)
    except service.VehiculoNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehículo no encontrado: {e}",
        ) from e


@router.post(
    "/vehiculos/{vehiculo_id}/incidencia",
    response_model=VehiculoResponse,
    summary="Reportar avería o pérdida de vehículo (CU-24)",
)
def reportar_incidencia_vehiculo(
    vehiculo_id: uuid.UUID,
    body: IncidenciaVehiculoRequest,
    session: SessionDep,
    _: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.INVENTARIO_REPORTAR_INCIDENCIA)),
    ],
):
    try:
        return service.reportar_incidencia_vehiculo(
            session,
            vehiculo_id,
            nuevo_estado=body.tipo,
            descripcion=body.descripcion,
        )
    except service.VehiculoNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehículo no encontrado: {e}",
        ) from e
    except service.EstadoIncidenciaInvalido as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    except service.MaterialEnEstadoFinal as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e


@router.post(
    "/vehiculos/{vehiculo_id}/reparar",
    response_model=VehiculoResponse,
    summary="Rehabilitar vehículo averiado (CU-24 nota)",
)
def reparar_vehiculo(
    vehiculo_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.INVENTARIO_REGISTRAR_VEHICULO)),
    ],
):
    try:
        return service.reparar_vehiculo(session, vehiculo_id)
    except service.VehiculoNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehículo no encontrado: {e}",
        ) from e
    except service.MaterialEnEstadoFinal as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e


# ---------------------------------------------------------------------------
# Asignación a servicio (CU-22)
# ---------------------------------------------------------------------------


@servicio_router.post(
    "/material",
    response_model=AsignacionMaterialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Asignar material a servicio (CU-22, US-05-06)",
)
def asignar_material_servicio(
    servicio_id: uuid.UUID,
    body: AsignarMaterialServicioRequest,
    session: SessionDep,
    _: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.INVENTARIO_ASIGNAR_A_SERVICIO)),
    ],
):
    try:
        asignacion = service.asignar_material_a_servicio(
            session,
            material_id=body.material_id,
            servicio_id=servicio_id,
            cantidad=body.cantidad,
        )
    except service.MaterialNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Material no encontrado: {e}",
        ) from e
    except service.MaterialNoOperativo as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    except service.TipoAsignacionNoCompatible as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    except service.CantidadInsuficiente as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    return _asignacion_to_response(asignacion)


@servicio_router.post(
    "/vehiculo",
    response_model=AsignacionVehiculoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Asignar vehículo a servicio (CU-22, US-05-07)",
)
def asignar_vehiculo_servicio(
    servicio_id: uuid.UUID,
    body: AsignarVehiculoServicioRequest,
    session: SessionDep,
    _: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.INVENTARIO_ASIGNAR_A_SERVICIO)),
    ],
):
    try:
        asignacion = service.asignar_vehiculo_a_servicio(
            session,
            vehiculo_id=body.vehiculo_id,
            servicio_id=servicio_id,
        )
    except service.VehiculoNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehículo no encontrado: {e}",
        ) from e
    except service.VehiculoYaAsignado as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    except service.VehiculoNoOperativo as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    return _asignacion_vehiculo_to_response(asignacion)
