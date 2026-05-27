"""Service del módulo inventario (EN-05-02 + EN-05-03 + EN-05-04).

Cubre CU-20 (registro), CU-21 (asignar a voluntario), CU-22 (asignar a
servicio), CU-23 (devolver) y CU-24 (incidencias).

Máquina de estados (EN-05-04)
-----------------------------

Estados del material/vehículo: OPERATIVO / AVERIADO / PERDIDO / EN_USO.

Transiciones aplicadas implícitamente por flujo:

- crear ........................ → OPERATIVO
- asignar (material/vehículo) ... requiere OPERATIVO o EN_USO con stock
  disponible (un material PRESTABLE puede tener varios asignados; un
  PERSONAL solo uno; un SERVICIO solo va a un servicio activo)
- devolver / liberar al cerrar .. quita asignación; el estado vuelve a
  OPERATIVO si ya no queda ninguna activa
- reportar_incidencia .......... → AVERIADO o PERDIDO desde cualquiera
- reparar ...................... AVERIADO → OPERATIVO (CU-24 nota: para
  rehabilitar un activo tras reparación)

PERDIDO es final (CU-24 nota): rehabilitar un activo perdido requiere
crear uno nuevo. La transición PERDIDO → cualquier otro estado se
rechaza en :class:`MaterialEnEstadoFinal`.

Excepciones de dominio
----------------------

- :class:`MaterialNoEncontrado` / :class:`VehiculoNoEncontrado` → 404
- :class:`AsignacionNoEncontrada` → 404
- :class:`MaterialNoOperativo` / :class:`VehiculoNoOperativo` → 409
- :class:`CantidadInsuficiente` → 409
- :class:`MaterialYaAsignadoAVoluntario` → 409
- :class:`VehiculoYaAsignado` → 409
- :class:`TipoAsignacionNoCompatible` → 409
- :class:`EstadoIncidenciaInvalido` → 422 (payload inválido)
- :class:`MaterialEnEstadoFinal` → 409
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlmodel import Session

from app.models.asignacion_material import AsignacionMaterial, TipoAsignacion
from app.models.asignacion_vehiculo import AsignacionVehiculo
from app.models.material import EstadoInventario, Material, TipoMaterial
from app.models.vehiculo import Vehiculo
from app.repositories import inventario as repo

if TYPE_CHECKING:
    from app.schemas.inventario import (
        MaterialCreate,
        MaterialUpdate,
        VehiculoCreate,
        VehiculoUpdate,
    )


# ---------------------------------------------------------------------------
# Excepciones de dominio
# ---------------------------------------------------------------------------


class InventarioError(Exception):
    """Base de las excepciones de dominio del módulo inventario."""


class MaterialNoEncontrado(InventarioError):  # noqa: N818 — castellano
    pass


class VehiculoNoEncontrado(InventarioError):  # noqa: N818 — castellano
    pass


class AsignacionNoEncontrada(InventarioError):  # noqa: N818 — castellano
    pass


class MaterialNoOperativo(InventarioError):  # noqa: N818 — castellano
    """El material no está en estado OPERATIVO y no puede asignarse."""


class VehiculoNoOperativo(InventarioError):  # noqa: N818 — castellano
    pass


class CantidadInsuficiente(InventarioError):  # noqa: N818 — castellano
    """No queda stock disponible para la asignación solicitada."""


class MaterialYaAsignadoAVoluntario(InventarioError):  # noqa: N818
    """El voluntario ya tiene una asignación activa de este material."""


class VehiculoYaAsignado(InventarioError):  # noqa: N818 — castellano
    """El vehículo ya está asignado a un servicio activo."""


class TipoAsignacionNoCompatible(InventarioError):  # noqa: N818
    """El tipo de asignación no encaja con el tipo del material."""


class EstadoIncidenciaInvalido(InventarioError):  # noqa: N818 — castellano
    """En reportar_incidencia el estado destino debe ser AVERIADO o PERDIDO."""


class MaterialEnEstadoFinal(InventarioError):  # noqa: N818 — castellano
    """El material/vehículo está en PERDIDO y no admite cambios de estado."""


# ---------------------------------------------------------------------------
# Lecturas
# ---------------------------------------------------------------------------


def listar_materiales(
    session: Session,
    *,
    skip: int = 0,
    limit: int = 50,
    q: str | None = None,
    estado: EstadoInventario | None = None,
    tipo: TipoMaterial | None = None,
    categoria: str | None = None,
) -> tuple[list[Material], int]:
    return repo.list_materiales(
        session,
        skip=skip,
        limit=limit,
        q=q,
        estado=estado,
        tipo=tipo,
        categoria=categoria,
    )


def obtener_material(session: Session, material_id: uuid.UUID) -> Material:
    material = repo.get_material(session, material_id)
    if material is None:
        raise MaterialNoEncontrado(str(material_id))
    return material


def listar_vehiculos(
    session: Session,
    *,
    skip: int = 0,
    limit: int = 50,
    q: str | None = None,
    estado: EstadoInventario | None = None,
    tipo=None,
) -> tuple[list[Vehiculo], int]:
    return repo.list_vehiculos(
        session, skip=skip, limit=limit, q=q, estado=estado, tipo=tipo
    )


def obtener_vehiculo(session: Session, vehiculo_id: uuid.UUID) -> Vehiculo:
    vehiculo = repo.get_vehiculo(session, vehiculo_id)
    if vehiculo is None:
        raise VehiculoNoEncontrado(str(vehiculo_id))
    return vehiculo


# ---------------------------------------------------------------------------
# Alta y edición de Material / Vehículo
# ---------------------------------------------------------------------------


def _generar_codigo_automatico(session: Session) -> str:
    """Genera un código `MAT-YYYYMMDD-XXXXXX` único (CU-20 paso 7)."""

    while True:
        sufijo = uuid.uuid4().hex[:6].upper()
        codigo = f"MAT-{datetime.now():%Y%m%d}-{sufijo}"
        if repo.get_material_por_codigo(session, codigo) is None:
            return codigo


def crear_material(session: Session, data: MaterialCreate) -> Material:
    """CU-20 / US-05-01. Genera código automático si el cliente no lo da."""

    payload = data.model_dump(exclude_unset=False)
    if not payload.get("codigo"):
        payload["codigo"] = _generar_codigo_automatico(session)
    payload["estado"] = EstadoInventario.OPERATIVO
    return repo.create_material(session, payload)


def actualizar_material(
    session: Session, material_id: uuid.UUID, data: MaterialUpdate
) -> Material:
    material = obtener_material(session, material_id)
    patch = data.model_dump(exclude_unset=True)
    return repo.update_material(session, material, patch)


def crear_vehiculo(session: Session, data: VehiculoCreate) -> Vehiculo:
    """CU-20 flujo A / US-05-02."""

    payload = data.model_dump(exclude_unset=False)
    payload["estado"] = EstadoInventario.OPERATIVO
    return repo.create_vehiculo(session, payload)


def actualizar_vehiculo(
    session: Session, vehiculo_id: uuid.UUID, data: VehiculoUpdate
) -> Vehiculo:
    vehiculo = obtener_vehiculo(session, vehiculo_id)
    patch = data.model_dump(exclude_unset=True)
    return repo.update_vehiculo(session, vehiculo, patch)


# ---------------------------------------------------------------------------
# Incidencias y reparación (EN-05-04 + CU-24)
# ---------------------------------------------------------------------------


_ESTADOS_INCIDENCIA = {EstadoInventario.AVERIADO, EstadoInventario.PERDIDO}


def reportar_incidencia_material(
    session: Session,
    material_id: uuid.UUID,
    *,
    nuevo_estado: EstadoInventario,
    descripcion: str,
) -> Material:
    """CU-24 / US-05-08 + US-05-09."""

    if nuevo_estado not in _ESTADOS_INCIDENCIA:
        raise EstadoIncidenciaInvalido(
            f"estado destino debe ser AVERIADO o PERDIDO; recibido {nuevo_estado}"
        )

    material = obtener_material(session, material_id)
    if material.estado == EstadoInventario.PERDIDO:
        raise MaterialEnEstadoFinal(
            "el material está en PERDIDO; ese estado es final"
        )
    return repo.set_estado_material(
        session,
        material,
        nuevo_estado=nuevo_estado,
        observaciones_incidencia=descripcion,
    )


def reportar_incidencia_vehiculo(
    session: Session,
    vehiculo_id: uuid.UUID,
    *,
    nuevo_estado: EstadoInventario,
    descripcion: str,
) -> Vehiculo:
    if nuevo_estado not in _ESTADOS_INCIDENCIA:
        raise EstadoIncidenciaInvalido(
            f"estado destino debe ser AVERIADO o PERDIDO; recibido {nuevo_estado}"
        )

    vehiculo = obtener_vehiculo(session, vehiculo_id)
    if vehiculo.estado == EstadoInventario.PERDIDO:
        raise MaterialEnEstadoFinal(
            "el vehículo está en PERDIDO; ese estado es final"
        )
    return repo.set_estado_vehiculo(
        session,
        vehiculo,
        nuevo_estado=nuevo_estado,
        observaciones_incidencia=descripcion,
    )


def reparar_material(session: Session, material_id: uuid.UUID) -> Material:
    """CU-24 nota: rehabilitar un material averiado (AVERIADO → OPERATIVO)."""

    material = obtener_material(session, material_id)
    if material.estado == EstadoInventario.PERDIDO:
        raise MaterialEnEstadoFinal(
            "el material está en PERDIDO; ese estado es final"
        )
    return repo.set_estado_material(
        session,
        material,
        nuevo_estado=EstadoInventario.OPERATIVO,
        observaciones_incidencia="",
    )


def reparar_vehiculo(session: Session, vehiculo_id: uuid.UUID) -> Vehiculo:
    vehiculo = obtener_vehiculo(session, vehiculo_id)
    if vehiculo.estado == EstadoInventario.PERDIDO:
        raise MaterialEnEstadoFinal(
            "el vehículo está en PERDIDO; ese estado es final"
        )
    return repo.set_estado_vehiculo(
        session,
        vehiculo,
        nuevo_estado=EstadoInventario.OPERATIVO,
        observaciones_incidencia="",
    )


# ---------------------------------------------------------------------------
# Asignaciones de material (CU-21 / CU-22)
# ---------------------------------------------------------------------------


_TIPOS_VOLUNTARIO = {TipoAsignacion.PERSONAL, TipoAsignacion.PRESTAMO}


def _validar_compatibilidad_tipo(
    material: Material, tipo_asignacion: TipoAsignacion
) -> None:
    """El tipo de asignación tiene que casar con el ``tipo`` del material."""

    if tipo_asignacion == TipoAsignacion.SERVICIO:
        if material.tipo != TipoMaterial.SERVICIO:
            raise TipoAsignacionNoCompatible(
                f"un material {material.tipo.value!r} no admite asignación a servicio"
            )
        return
    # Asignación a voluntario.
    if material.tipo == TipoMaterial.SERVICIO:
        raise TipoAsignacionNoCompatible(
            "un material de servicio no se asigna a un voluntario"
        )
    if tipo_asignacion == TipoAsignacion.PERSONAL:
        if material.tipo != TipoMaterial.PERSONAL:
            raise TipoAsignacionNoCompatible(
                "asignación PERSONAL requiere un material de tipo PERSONAL"
            )
    if tipo_asignacion == TipoAsignacion.PRESTAMO:
        if material.tipo != TipoMaterial.PRESTABLE:
            raise TipoAsignacionNoCompatible(
                "asignación PRESTAMO requiere un material de tipo PRESTABLE"
            )


def asignar_material_a_voluntario(
    session: Session,
    *,
    material_id: uuid.UUID,
    voluntario_id: uuid.UUID,
    tipo: TipoAsignacion,
    cantidad: int = 1,
    cuando: datetime | None = None,
) -> AsignacionMaterial:
    """CU-21 / US-05-03 (PERSONAL) y US-05-04 (PRESTAMO)."""

    if tipo not in _TIPOS_VOLUNTARIO:
        raise TipoAsignacionNoCompatible(
            "tipo debe ser PERSONAL o PRESTAMO para asignar a voluntario"
        )

    material = obtener_material(session, material_id)
    if material.estado not in (EstadoInventario.OPERATIVO, EstadoInventario.EN_USO):
        raise MaterialNoOperativo(
            f"material en estado {material.estado.value}; no se puede asignar"
        )
    _validar_compatibilidad_tipo(material, tipo)

    if (
        repo.get_asignacion_activa_material_voluntario(
            session, material_id=material_id, voluntario_id=voluntario_id
        )
        is not None
    ):
        raise MaterialYaAsignadoAVoluntario(
            f"el voluntario {voluntario_id} ya tiene activa una asignación de "
            f"este material"
        )

    asignadas = repo.count_unidades_asignadas_material(
        session, material_id, excluir_tipo=TipoAsignacion.SERVICIO
    )
    if asignadas + cantidad > material.cantidad:
        raise CantidadInsuficiente(
            f"no queda stock: solicitadas {cantidad}, "
            f"asignadas {asignadas}/{material.cantidad}"
        )

    asignacion = repo.create_asignacion_material(
        session,
        data=dict(
            material_id=material_id,
            voluntario_id=voluntario_id,
            servicio_id=None,
            tipo=tipo,
            cantidad=cantidad,
            fecha_asignacion=cuando or datetime.now(),
        ),
    )
    # Stock totalmente consumido → EN_USO.
    if asignadas + cantidad == material.cantidad:
        repo.set_estado_material(
            session, material, nuevo_estado=EstadoInventario.EN_USO
        )
    return asignacion


def asignar_material_a_servicio(
    session: Session,
    *,
    material_id: uuid.UUID,
    servicio_id: uuid.UUID,
    cantidad: int = 1,
    cuando: datetime | None = None,
) -> AsignacionMaterial:
    """CU-22 / US-05-06."""

    material = obtener_material(session, material_id)
    if material.estado not in (EstadoInventario.OPERATIVO, EstadoInventario.EN_USO):
        raise MaterialNoOperativo(
            f"material en estado {material.estado.value}; no se puede asignar"
        )
    _validar_compatibilidad_tipo(material, TipoAsignacion.SERVICIO)

    asignadas_no_servicio = repo.count_unidades_asignadas_material(
        session, material_id, excluir_tipo=TipoAsignacion.SERVICIO
    )
    stock_para_servicio = material.cantidad - asignadas_no_servicio
    if cantidad > stock_para_servicio:
        raise CantidadInsuficiente(
            f"stock insuficiente: solicitadas {cantidad}, "
            f"disponibles para servicio {stock_para_servicio}"
        )

    asignacion = repo.create_asignacion_material(
        session,
        data=dict(
            material_id=material_id,
            voluntario_id=None,
            servicio_id=servicio_id,
            tipo=TipoAsignacion.SERVICIO,
            cantidad=cantidad,
            fecha_asignacion=cuando or datetime.now(),
        ),
    )
    return asignacion


def devolver_material(
    session: Session,
    *,
    material_id: uuid.UUID,
    voluntario_id: uuid.UUID,
    observaciones: str | None = None,
    cuando: datetime | None = None,
) -> AsignacionMaterial:
    """CU-23 / US-05-05. Devuelve la asignación activa al voluntario."""

    material = obtener_material(session, material_id)  # 404 si no existe

    asignacion = repo.get_asignacion_activa_material_voluntario(
        session, material_id=material_id, voluntario_id=voluntario_id
    )
    if asignacion is None:
        raise AsignacionNoEncontrada(
            f"no hay asignación activa de {material_id} a {voluntario_id}"
        )

    cerrada = repo.cerrar_asignacion_material(
        session,
        asignacion,
        cuando=cuando or datetime.now(),
        observaciones_devolucion=observaciones,
    )

    # Tras devolver: si el material estaba EN_USO y ya no queda stock
    # consumido fuera de servicio, vuelve a OPERATIVO.
    if material.estado == EstadoInventario.EN_USO:
        restantes = repo.count_unidades_asignadas_material(
            session, material_id, excluir_tipo=TipoAsignacion.SERVICIO
        )
        if restantes < material.cantidad:
            repo.set_estado_material(
                session, material, nuevo_estado=EstadoInventario.OPERATIVO
            )

    return cerrada


# ---------------------------------------------------------------------------
# Asignaciones de vehículo (CU-22 / US-05-07)
# ---------------------------------------------------------------------------


def asignar_vehiculo_a_servicio(
    session: Session,
    *,
    vehiculo_id: uuid.UUID,
    servicio_id: uuid.UUID,
    cuando: datetime | None = None,
) -> AsignacionVehiculo:
    vehiculo = obtener_vehiculo(session, vehiculo_id)
    # Orden de checks: primero "ya asignado", luego "no operativo".
    # Si está EN_USO por una asignación previa, lo razonable es decirle
    # al cliente "ese vehículo está ocupado" (causa primaria) antes que
    # "no está operativo" (síntoma del flujo anterior).
    if (
        repo.get_asignacion_activa_vehiculo(session, vehiculo_id) is not None
    ):
        raise VehiculoYaAsignado(
            f"el vehículo {vehiculo_id} ya está asignado a un servicio activo"
        )
    if vehiculo.estado != EstadoInventario.OPERATIVO:
        raise VehiculoNoOperativo(
            f"vehículo en estado {vehiculo.estado.value}; no se puede asignar"
        )

    asignacion = repo.create_asignacion_vehiculo(
        session,
        data=dict(
            vehiculo_id=vehiculo_id,
            servicio_id=servicio_id,
            fecha_asignacion=cuando or datetime.now(),
        ),
    )
    # Vehículo único: pasa a EN_USO.
    repo.set_estado_vehiculo(
        session, vehiculo, nuevo_estado=EstadoInventario.EN_USO
    )
    return asignacion


# ---------------------------------------------------------------------------
# Liberación al cerrar servicio (US-05-06 / US-05-07 — gancho para E03)
# ---------------------------------------------------------------------------


def liberar_asignaciones_de_servicio(
    session: Session,
    *,
    servicio_id: uuid.UUID,
    cuando: datetime,
) -> tuple[list[AsignacionMaterial], list[AsignacionVehiculo]]:
    """Cierra las asignaciones activas de material y vehículo al cerrar servicio.

    Material vuelve a OPERATIVO; vehículo también si no queda otra
    asignación activa (debería ser siempre el caso porque UNIQUE
    implícito en vehículos vía estado EN_USO).
    """

    materiales_cerrados: list[AsignacionMaterial] = []
    for asignacion in repo.list_asignaciones_activas_servicio_material(
        session, servicio_id
    ):
        cerrada = repo.cerrar_asignacion_material(
            session, asignacion, cuando=cuando
        )
        materiales_cerrados.append(cerrada)
        # Si el material estaba EN_USO sin más asignaciones activas, OPERATIVO.
        material = repo.get_material(session, asignacion.material_id)
        if material is not None and material.estado == EstadoInventario.EN_USO:
            restantes = repo.count_unidades_asignadas_material(
                session, material.id
            )
            if restantes == 0:
                repo.set_estado_material(
                    session,
                    material,
                    nuevo_estado=EstadoInventario.OPERATIVO,
                )

    vehiculos_cerrados: list[AsignacionVehiculo] = []
    for asignacion in repo.list_asignaciones_activas_servicio_vehiculo(
        session, servicio_id
    ):
        cerrada = repo.cerrar_asignacion_vehiculo(
            session, asignacion, cuando=cuando
        )
        vehiculos_cerrados.append(cerrada)
        vehiculo = repo.get_vehiculo(session, asignacion.vehiculo_id)
        if vehiculo is not None and vehiculo.estado == EstadoInventario.EN_USO:
            repo.set_estado_vehiculo(
                session, vehiculo, nuevo_estado=EstadoInventario.OPERATIVO
            )

    return materiales_cerrados, vehiculos_cerrados
