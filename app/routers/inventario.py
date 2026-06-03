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
from datetime import datetime
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
    AsignacionActualResponse,
    AsignacionMaterialResponse,
    AsignacionVehiculoResponse,
    AsignarDotacionVehiculoRequest,
    AsignarMaterialServicioRequest,
    AsignarMaterialVoluntarioRequest,
    AsignarVehiculoServicioRequest,
    DevolverMaterialRequest,
    DotacionVehiculoResponse,
    IncidenciaMaterialRequest,
    IncidenciaVehiculoRequest,
    InventarioMaterialServicioResponse,
    InventarioServicioResponse,
    InventarioVehiculoServicioResponse,
    MaterialCreate,
    MaterialResponse,
    MaterialSummary,
    MaterialUpdate,
    OcupacionRecursoResponse,
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


def _conflictos_json(conflictos: list[dict]) -> list[dict]:
    """Serializa los conflictos de solape a tipos JSON-safe (PR6).

    El ``detail`` de una ``HTTPException`` se serializa con el JSON encoder
    por defecto, que no sabe de ``UUID`` ni ``datetime``; los convertimos a
    ``str`` / ISO-8601 a mano para que el cliente reciba el detalle del
    conflicto sin un 500.
    """

    return [
        {
            "servicio_id": str(c["servicio_id"]),
            "fecha_inicio": c["fecha_inicio"].isoformat(),
            "fecha_fin": (
                c["fecha_fin"].isoformat() if c["fecha_fin"] is not None else None
            ),
        }
        for c in conflictos
    ]


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


def _dotacion_to_response(asignacion) -> DotacionVehiculoResponse:
    return DotacionVehiculoResponse(
        id=asignacion.id,
        material_id=asignacion.material_id,
        material_nombre=asignacion.material.nombre,
        cantidad=asignacion.cantidad,
        fecha_asignacion=asignacion.fecha_asignacion,
    )


def _inventario_material_servicio_response(
    asignacion,
) -> InventarioMaterialServicioResponse:
    return InventarioMaterialServicioResponse(
        id=asignacion.id,
        material_id=asignacion.material_id,
        material_nombre=asignacion.material.nombre,
        cantidad=asignacion.cantidad,
        fecha_asignacion=asignacion.fecha_asignacion,
    )


def _inventario_vehiculo_servicio_response(
    asignacion,
) -> InventarioVehiculoServicioResponse:
    return InventarioVehiculoServicioResponse(
        id=asignacion.id,
        vehiculo_id=asignacion.vehiculo_id,
        codigo_interno=asignacion.vehiculo.codigo_interno,
        matricula=asignacion.vehiculo.matricula,
        fecha_asignacion=asignacion.fecha_asignacion,
    )


def _material_detail_response(
    material, asignaciones, unidades: int
) -> MaterialResponse:
    """Ensambla la response de DETALLE de material con trazabilidad (PR1)."""

    activas = [
        AsignacionActualResponse(
            tipo=a.tipo.value,
            voluntario_id=a.voluntario_id,
            servicio_id=a.servicio_id,
            vehiculo_id=a.vehiculo_id,
            cantidad=a.cantidad,
            fecha_asignacion=a.fecha_asignacion,
        )
        for a in asignaciones
    ]
    return MaterialResponse.model_validate(material).model_copy(
        update={
            "asignaciones_activas": activas,
            "unidades_asignadas": unidades,
        }
    )


def _vehiculo_detail_response(vehiculo, asignacion) -> VehiculoResponse:
    """Ensambla la response de DETALLE de vehículo con trazabilidad (PR1)."""

    actual = None
    if asignacion is not None:
        actual = AsignacionActualResponse(
            tipo="servicio",
            servicio_id=asignacion.servicio_id,
            servicio_titulo=(
                asignacion.servicio.titulo if asignacion.servicio else None
            ),
            cantidad=1,
            fecha_asignacion=asignacion.fecha_asignacion,
        )
    return VehiculoResponse.model_validate(vehiculo).model_copy(
        update={"asignacion_actual": actual}
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
        material = service.obtener_material(session, material_id)
    except service.MaterialNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Material no encontrado: {e}",
        ) from e
    asignaciones, unidades = service.trazabilidad_material(session, material_id)
    return _material_detail_response(material, asignaciones, unidades)


@router.get(
    "/material/{material_id}/ocupacion",
    response_model=OcupacionRecursoResponse,
    summary="Consultar ocupación temporal de un material (PR6)",
)
def ocupacion_material(
    material_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[
        CurrentUser, Depends(require_permission(Permission.INVENTARIO_VER))
    ],
    desde: datetime = Query(..., description="Inicio del intervalo [desde, hasta)"),
    hasta: datetime = Query(..., description="Fin del intervalo (exclusivo)"),
    cantidad: int = Query(1, ge=1, description="Unidades que se quieren reservar"),
    excluir_servicio_id: uuid.UUID | None = Query(
        None,
        description="Servicio a excluir del cálculo (p.ej. el propio destino)",
    ),
):
    """Indica si quedan ``cantidad`` unidades libres en ``[desde, hasta)`` (PR6).

    A diferencia del vehículo, ``disponible`` depende del stock: ``True`` si
    las unidades reservadas por servicios solapados más las solicitadas no
    superan el stock total. ``conflictos`` lista los servicios en solape.
    """

    if hasta <= desde:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'hasta' debe ser estrictamente posterior a 'desde'",
        )
    try:
        disponible, conflictos = service.ocupacion_material(
            session,
            material_id=material_id,
            desde=desde,
            hasta=hasta,
            cantidad=cantidad,
            excluir_servicio_id=excluir_servicio_id,
        )
    except service.MaterialNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Material no encontrado: {e}",
        ) from e
    return OcupacionRecursoResponse(disponible=disponible, conflictos=conflictos)


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
    try:
        return service.crear_material(session, data)
    except service.UbicacionBaseNoEncontrada as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"La ubicación indicada no existe: {e}",
        ) from e


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
    except service.UbicacionBaseNoEncontrada as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"La ubicación indicada no existe: {e}",
        ) from e


@router.delete(
    "/material/{material_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar material (borrado físico, solo si nunca se asignó)",
)
def eliminar_material(
    material_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.INVENTARIO_REGISTRAR_MATERIAL)),
    ],
):
    """Borra un material para corregir errores de alta.

    Mismo permiso que registrar/editar (quien da de alta el recurso lo
    gestiona). Solo procede si el material no tiene ninguna asignación
    (activa o histórica); en caso contrario la baja correcta es reportar la
    incidencia (CU-24), que conserva el histórico para auditoría (409).
    """

    try:
        service.eliminar_material(session, material_id)
    except service.MaterialNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Material no encontrado: {e}",
        ) from e
    except service.MaterialEnUso as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
            actor_keycloak_id=user.sub,
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
    user: Annotated[
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
            actor_keycloak_id=user.sub,
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
        vehiculo = service.obtener_vehiculo(session, vehiculo_id)
    except service.VehiculoNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehículo no encontrado: {e}",
        ) from e
    asignacion = service.trazabilidad_vehiculo(session, vehiculo_id)
    return _vehiculo_detail_response(vehiculo, asignacion)


@router.get(
    "/vehiculos/{vehiculo_id}/ocupacion",
    response_model=OcupacionRecursoResponse,
    summary="Consultar ocupación temporal de un vehículo (PR6)",
)
def ocupacion_vehiculo(
    vehiculo_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[
        CurrentUser, Depends(require_permission(Permission.INVENTARIO_VER))
    ],
    desde: datetime = Query(..., description="Inicio del intervalo [desde, hasta)"),
    hasta: datetime = Query(..., description="Fin del intervalo (exclusivo)"),
    excluir_servicio_id: uuid.UUID | None = Query(
        None,
        description="Servicio a excluir del cálculo (p.ej. el propio destino)",
    ),
):
    """Indica si el vehículo está libre en ``[desde, hasta)`` (PR6).

    Devuelve ``disponible`` (sin solape) y la lista de ``conflictos``
    (servicios PUBLICADO/ACTIVO con intervalo cerrado que solapan).
    """

    if hasta <= desde:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'hasta' debe ser estrictamente posterior a 'desde'",
        )
    try:
        disponible, conflictos = service.ocupacion_vehiculo(
            session,
            vehiculo_id=vehiculo_id,
            desde=desde,
            hasta=hasta,
            excluir_servicio_id=excluir_servicio_id,
        )
    except service.VehiculoNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehículo no encontrado: {e}",
        ) from e
    return OcupacionRecursoResponse(disponible=disponible, conflictos=conflictos)


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
    try:
        return service.crear_vehiculo(session, data)
    except service.UbicacionBaseNoEncontrada as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"La ubicación indicada no existe: {e}",
        ) from e


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
    except service.UbicacionBaseNoEncontrada as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"La ubicación indicada no existe: {e}",
        ) from e


@router.delete(
    "/vehiculos/{vehiculo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar vehículo (borrado físico, solo si nunca se asignó)",
)
def eliminar_vehiculo(
    vehiculo_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.INVENTARIO_REGISTRAR_VEHICULO)),
    ],
):
    """Borra un vehículo para corregir errores de alta.

    Mismo permiso que registrar/editar (quien da de alta el recurso lo
    gestiona). Solo procede si el vehículo no tiene ninguna asignación —ni a
    servicio ni como dotación de material— (activa o histórica); en caso
    contrario la baja correcta es reportar la incidencia (CU-24), que
    conserva el histórico para auditoría (409).
    """

    try:
        service.eliminar_vehiculo(session, vehiculo_id)
    except service.VehiculoNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehículo no encontrado: {e}",
        ) from e
    except service.VehiculoEnUso as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
# Vehículo — Dotación fija de material (PR3 / SP-09)
# ---------------------------------------------------------------------------


@router.get(
    "/vehiculos/{vehiculo_id}/dotacion",
    response_model=list[DotacionVehiculoResponse],
    summary="Listar dotación fija de un vehículo (PR3)",
)
def listar_dotacion_vehiculo(
    vehiculo_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[
        CurrentUser, Depends(require_permission(Permission.INVENTARIO_VER))
    ],
):
    try:
        dotaciones = service.listar_dotacion_vehiculo(session, vehiculo_id)
    except service.VehiculoNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehículo no encontrado: {e}",
        ) from e
    return [_dotacion_to_response(d) for d in dotaciones]


@router.post(
    "/vehiculos/{vehiculo_id}/dotacion",
    response_model=DotacionVehiculoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Asignar dotación fija a un vehículo (PR3)",
)
def asignar_dotacion_vehiculo(
    vehiculo_id: uuid.UUID,
    body: AsignarDotacionVehiculoRequest,
    session: SessionDep,
    _: Annotated[
        CurrentUser,
        Depends(
            require_permission(
                Permission.INVENTARIO_GESTIONAR_DOTACION_VEHICULO
            )
        ),
    ],
):
    try:
        asignacion = service.asignar_dotacion_vehiculo(
            session,
            vehiculo_id=vehiculo_id,
            material_id=body.material_id,
            cantidad=body.cantidad,
        )
    except service.VehiculoNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehículo no encontrado: {e}",
        ) from e
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
    # `material` ya viene cargado en la sesión tras crear la asignación;
    # refrescamos la relación para que el builder no dispare otra query.
    session.refresh(asignacion, attribute_names=["material"])
    return _dotacion_to_response(asignacion)


@router.delete(
    "/vehiculos/{vehiculo_id}/dotacion/{asignacion_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Liberar dotación fija de un vehículo (PR3)",
)
def liberar_dotacion_vehiculo(
    vehiculo_id: uuid.UUID,
    asignacion_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[
        CurrentUser,
        Depends(
            require_permission(
                Permission.INVENTARIO_GESTIONAR_DOTACION_VEHICULO
            )
        ),
    ],
):
    try:
        service.liberar_dotacion_vehiculo(
            session,
            vehiculo_id=vehiculo_id,
            asignacion_id=asignacion_id,
        )
    except service.VehiculoNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehículo no encontrado: {e}",
        ) from e
    except service.AsignacionNoEncontrada as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    except service.ServicioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Servicio no encontrado: {e}",
        ) from e
    except service.ServicioCerrado as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
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
    except service.MaterialSolapado as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"mensaje": str(e), "conflictos": _conflictos_json(e.conflictos)},
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
    except service.ServicioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Servicio no encontrado: {e}",
        ) from e
    except service.ServicioCerrado as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    except service.VehiculoOcupado as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"mensaje": str(e), "conflictos": _conflictos_json(e.conflictos)},
        ) from e
    except service.VehiculoNoOperativo as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    return _asignacion_vehiculo_to_response(asignacion)


@servicio_router.get(
    "",
    response_model=InventarioServicioResponse,
    summary="Listar recursos asignados a un servicio (R1, lectura)",
)
def listar_inventario_servicio(
    servicio_id: uuid.UUID,
    session: SessionDep,
    # La lectura de los recursos del PROPIO servicio se gatea por
    # `servicios.ver_publicados` (que el voluntario raso tiene), no por
    # `inventario.ver`: un voluntario inscrito puede ver qué material y
    # vehículos lleva su servicio sin acceder al inventario global (B5).
    _: Annotated[
        CurrentUser,
        Depends(require_permission(Permission.SERVICIOS_VER_PUBLICADOS)),
    ],
):
    try:
        material, vehiculos = service.listar_inventario_de_servicio(
            session, servicio_id=servicio_id
        )
    except service.ServicioNoEncontrado as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Servicio no encontrado: {e}",
        ) from e
    return InventarioServicioResponse(
        material=[
            _inventario_material_servicio_response(a) for a in material
        ],
        vehiculos=[
            _inventario_vehiculo_servicio_response(a) for a in vehiculos
        ],
    )
