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
- :class:`ServicioCerrado` → 409 (no se asignan recursos a servicios cerrados)
- :class:`MaterialEnUso` → 409 (borrado físico de material con asignaciones)
- :class:`VehiculoEnUso` → 409 (borrado físico de vehículo con asignaciones)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlmodel import Session

from app.models.asignacion_material import AsignacionMaterial, TipoAsignacion
from app.models.asignacion_vehiculo import AsignacionVehiculo
from app.models.material import EstadoInventario, Material, TipoMaterial
from app.models.servicio import EstadoServicio, Servicio, TipoServicio
from app.models.vehiculo import Vehiculo
from app.repositories import inventario as repo
from app.repositories import servicios as servicios_repo
from app.repositories import ubicaciones as ubicaciones_repo

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


class ServicioNoEncontrado(InventarioError):  # noqa: N818 — castellano
    """El servicio destino de la asignación no existe."""


class ServicioCerrado(InventarioError):  # noqa: N818 — castellano
    """El servicio destino está CERRADO y no admite nuevas asignaciones."""


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


class UbicacionBaseNoEncontrada(InventarioError):  # noqa: N818 — castellano
    """El ``ubicacion_base_id`` del body no existe en el catálogo (PR2)."""


class RecursoSolapado(InventarioError):  # noqa: N818 — castellano
    """Un recurso ya está comprometido en otro servicio en el mismo intervalo.

    Base de los conflictos de disponibilidad temporal (PR6 / Política A).
    Lleva ``conflictos``: lista de ``{servicio_id, fecha_inicio, fecha_fin}``
    de los servicios que solapan el intervalo solicitado, para que el router
    pueda devolverlos al cliente.
    """

    def __init__(self, message: str, conflictos: list[dict]) -> None:
        super().__init__(message)
        self.conflictos = conflictos


class VehiculoOcupado(RecursoSolapado):  # noqa: N818 — castellano
    """El vehículo ya está asignado a otro servicio que solapa el intervalo."""


class MaterialSolapado(RecursoSolapado):  # noqa: N818 — castellano
    """No quedan unidades de material libres en el intervalo solicitado."""


class MaterialEnUso(InventarioError):  # noqa: N818 — castellano
    """El material tiene asignaciones (a voluntario, servicio o vehículo) y no
    admite borrado físico.

    El borrado se reserva para corregir errores de alta de un material que
    nunca llegó a usarse. Cualquier fila ``AsignacionMaterial`` (activa o
    histórica) bloquearía el DELETE por la FK ``materiales.id``; se comprueba
    antes para devolver un 409 con un mensaje claro.
    """


class VehiculoEnUso(InventarioError):  # noqa: N818 — castellano
    """El vehículo tiene asignaciones (a servicio o como dotación de material)
    y no admite borrado físico.

    Análogo a :class:`MaterialEnUso`: tanto una ``AsignacionVehiculo`` como
    una ``AsignacionMaterial`` de dotación referencian al vehículo por FK
    (sin ON DELETE CASCADE) y bloquearían el DELETE.
    """


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
# Trazabilidad del estado actual (PR1) — sólo para responses de DETALLE
# ---------------------------------------------------------------------------


def trazabilidad_material(
    session: Session, material_id: uuid.UUID
) -> tuple[list[AsignacionMaterial], int]:
    """Asignaciones activas de un material y la suma de sus cantidades (PR1).

    Devuelve la lista cruda de :class:`AsignacionMaterial` activas (sin
    devolver) más ``unidades_asignadas`` (suma de ``cantidad``). El
    ensamblado a schema vive en el router. Sólo se invoca desde el GET de
    detalle: el listado (Summary) no lo expone para no disparar N+1.
    """

    activas = repo.list_asignaciones_activas_material(session, material_id)
    unidades = sum(a.cantidad for a in activas)
    return activas, unidades


def trazabilidad_vehiculo(
    session: Session, vehiculo_id: uuid.UUID
) -> AsignacionVehiculo | None:
    """Asignación a servicio activa de un vehículo, o ``None`` (PR1).

    El vehículo es unidad única, así que la asignación es singular. El
    servicio viene precargado (``selectinload``) para aplanar el título
    sin un segundo viaje a BD.
    """

    return repo.get_asignacion_activa_vehiculo_con_servicio(
        session, vehiculo_id
    )


# ---------------------------------------------------------------------------
# Disponibilidad temporal / no-solape de recursos (PR6 / Política A)
# ---------------------------------------------------------------------------
#
# Política A (confirmada por el PO):
#
# 1. Solape semiabierto ``[inicio, fin)``: dos intervalos solapan sii
#    ``inicio_A < fin_B AND inicio_B < fin_A``. Encadenados (``fin_A ==
#    inicio_B``) NO solapan.
# 2. ``fecha_fin`` NULL no reserva: ni el intervalo existente ni el nuevo
#    cuentan para el solape si su fin es abierto. Se gestiona a mano.
# 3. Borrador no reserva: sólo PUBLICADO / ACTIVO bloquean (filtro en repo).
# 4. Emergencia hace override: si el servicio destino es EMERGENCIA se
#    permite la asignación pese a solapar un preventivo. NO se libera
#    automáticamente la asignación del otro servicio (gestión humana).


def _conflictos_payload(servicios: list[Servicio]) -> list[dict]:
    """Serializa los servicios en conflicto para la excepción / la response."""

    return [
        {
            "servicio_id": s.id,
            "fecha_inicio": s.fecha_inicio,
            "fecha_fin": s.fecha_fin,
        }
        for s in servicios
    ]


def _obtener_servicio(session: Session, servicio_id: uuid.UUID) -> Servicio:
    servicio = servicios_repo.get(session, servicio_id)
    if servicio is None:
        raise ServicioNoEncontrado(str(servicio_id))
    return servicio


def ocupacion_vehiculo(
    session: Session,
    *,
    vehiculo_id: uuid.UUID,
    desde: datetime,
    hasta: datetime,
    excluir_servicio_id: uuid.UUID | None = None,
) -> tuple[bool, list[dict]]:
    """Consulta de ocupación de un vehículo en ``[desde, hasta)`` (PR6).

    Devuelve ``(disponible, conflictos)``. ``disponible`` es ``True`` si no
    hay ningún servicio que reserve y solape el intervalo. ``conflictos`` es
    la lista de ``{servicio_id, fecha_inicio, fecha_fin}`` en solape.
    """

    obtener_vehiculo(session, vehiculo_id)  # 404 si no existe
    conflictos = repo.find_servicios_solapados_vehiculo(
        session,
        vehiculo_id=vehiculo_id,
        inicio=desde,
        fin=hasta,
        excluir_servicio_id=excluir_servicio_id,
    )
    return (len(conflictos) == 0, _conflictos_payload(conflictos))


def listar_vehiculos_disponibles_para_servicio(
    session: Session,
    *,
    servicio_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
    q: str | None = None,
    tipo=None,
) -> tuple[list[Vehiculo], int]:
    """Vehículos disponibles para un servicio en su intervalo (picker).

    Reutiliza la Política A: descarta los vehículos no operativos
    (AVERIADO / PERDIDO, ya filtrados en el repo) y los que solapan el
    intervalo ``[servicio.fecha_inicio, servicio.fecha_fin)`` del servicio
    destino. El solape se evalúa con la misma consulta que
    :func:`ocupacion_vehiculo` (``repo.find_servicios_solapados_vehiculo``),
    excluyendo el propio servicio del cálculo. Si el servicio tiene
    ``fecha_fin`` NULL no se evalúa solape (regla 2 de Política A): sólo se
    filtra por estado.

    El servicio destino debe existir (``ServicioNoEncontrado`` → 404). La
    paginación (``skip`` / ``limit``) se aplica sobre el conjunto ya
    filtrado para que el cliente reciba ``X-Total-Count`` coherente con la
    disponibilidad real.
    """

    servicio = _obtener_servicio(session, servicio_id)

    candidatos = repo.list_vehiculos_candidatos_disponibilidad(
        session, q=q, tipo=tipo
    )

    # Sin intervalo cerrado no se evalúa solape: todos los operativos valen.
    if servicio.fecha_fin is None:
        disponibles = candidatos
    else:
        disponibles = [
            vehiculo
            for vehiculo in candidatos
            if not repo.find_servicios_solapados_vehiculo(
                session,
                vehiculo_id=vehiculo.id,
                inicio=servicio.fecha_inicio,
                fin=servicio.fecha_fin,
                excluir_servicio_id=servicio_id,
            )
        ]

    total = len(disponibles)
    return disponibles[skip : skip + limit], total


def listar_materiales_disponibles_para_servicio(
    session: Session,
    *,
    servicio_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
    q: str | None = None,
    tipo: TipoMaterial | None = None,
    categoria: str | None = None,
) -> tuple[list[Material], int]:
    """Materiales con unidades libres para un servicio en su intervalo (picker).

    Reutiliza la Política A: descarta el material no operativo (AVERIADO /
    PERDIDO, ya filtrado en el repo) y el que no tiene ninguna unidad libre
    en el intervalo del servicio destino, asumiendo que el picker pide UNA
    unidad. El cálculo de unidades libres es el mismo que en
    :func:`asignar_material_a_servicio`: el stock total menos lo
    comprometido globalmente fuera de servicio (PERSONAL / PRESTAMO /
    DOTACION_VEHICULO) menos lo reservado por servicios que solapan el
    intervalo. Si el servicio tiene ``fecha_fin`` NULL no se evalúa solape
    (regla 2): sólo cuenta el stock global comprometido.

    El servicio destino debe existir (``ServicioNoEncontrado`` → 404). La
    paginación se aplica sobre el conjunto ya filtrado.
    """

    servicio = _obtener_servicio(session, servicio_id)
    evaluar_solape = servicio.fecha_fin is not None

    disponibles: list[Material] = []
    for material in repo.list_materiales_candidatos_disponibilidad(
        session, q=q, tipo=tipo, categoria=categoria
    ):
        comprometidas_no_servicio = repo.count_unidades_asignadas_material(
            session, material.id, excluir_tipo=TipoAsignacion.SERVICIO
        )
        reservadas_solapadas = 0
        if evaluar_solape:
            solapes = repo.find_solapes_material(
                session,
                material_id=material.id,
                inicio=servicio.fecha_inicio,
                fin=servicio.fecha_fin,
                excluir_servicio_id=servicio_id,
            )
            reservadas_solapadas = sum(unidades for _, unidades in solapes)
        libres = (
            material.cantidad
            - comprometidas_no_servicio
            - reservadas_solapadas
        )
        # El picker reserva una unidad: basta con que quede al menos una.
        if libres >= 1:
            disponibles.append(material)

    total = len(disponibles)
    return disponibles[skip : skip + limit], total


def ocupacion_material(
    session: Session,
    *,
    material_id: uuid.UUID,
    desde: datetime,
    hasta: datetime,
    cantidad: int = 1,
    excluir_servicio_id: uuid.UUID | None = None,
) -> tuple[bool, list[dict]]:
    """Consulta de ocupación de un material en ``[desde, hasta)`` (PR6).

    El material es stock: ``disponible`` es ``True`` si las unidades ya
    reservadas por servicios solapados más la ``cantidad`` solicitada no
    superan el stock total del material. ``conflictos`` lista los servicios
    que solapan (con cualquier reserva), independientemente de si el stock
    alcanza o no, para dar visibilidad de quién comparte el intervalo.
    """

    material = obtener_material(session, material_id)
    solapes = repo.find_solapes_material(
        session,
        material_id=material_id,
        inicio=desde,
        fin=hasta,
        excluir_servicio_id=excluir_servicio_id,
    )
    reservadas = sum(unidades for _, unidades in solapes)
    disponible = reservadas + cantidad <= material.cantidad
    conflictos = _conflictos_payload([servicio for servicio, _ in solapes])
    return (disponible, conflictos)


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


def _validar_ubicacion_base(
    session: Session, ubicacion_base_id: uuid.UUID | None
) -> None:
    """Verifica que el ``ubicacion_base_id`` del body existe (PR2).

    ``None`` es válido (la ubicación es opcional y se admite desvincular).
    Un id que no apunta a ninguna fila del catálogo se rechaza antes de
    llegar al constraint de BD para devolver un 422 limpio.
    """

    if ubicacion_base_id is None:
        return
    if ubicaciones_repo.get_ubicacion(session, ubicacion_base_id) is None:
        raise UbicacionBaseNoEncontrada(str(ubicacion_base_id))


def crear_material(session: Session, data: MaterialCreate) -> Material:
    """CU-20 / US-05-01. Genera código automático si el cliente no lo da."""

    payload = data.model_dump(exclude_unset=False)
    _validar_ubicacion_base(session, payload.get("ubicacion_base_id"))
    if not payload.get("codigo"):
        payload["codigo"] = _generar_codigo_automatico(session)
    payload["estado"] = EstadoInventario.OPERATIVO
    return repo.create_material(session, payload)


def actualizar_material(
    session: Session, material_id: uuid.UUID, data: MaterialUpdate
) -> Material:
    material = obtener_material(session, material_id)
    patch = data.model_dump(exclude_unset=True)
    _validar_ubicacion_base(session, patch.get("ubicacion_base_id"))
    return repo.update_material(session, material, patch)


def crear_vehiculo(session: Session, data: VehiculoCreate) -> Vehiculo:
    """CU-20 flujo A / US-05-02."""

    payload = data.model_dump(exclude_unset=False)
    _validar_ubicacion_base(session, payload.get("ubicacion_base_id"))
    payload["estado"] = EstadoInventario.OPERATIVO
    return repo.create_vehiculo(session, payload)


def actualizar_vehiculo(
    session: Session, vehiculo_id: uuid.UUID, data: VehiculoUpdate
) -> Vehiculo:
    vehiculo = obtener_vehiculo(session, vehiculo_id)
    patch = data.model_dump(exclude_unset=True)
    _validar_ubicacion_base(session, patch.get("ubicacion_base_id"))
    return repo.update_vehiculo(session, vehiculo, patch)


def eliminar_material(session: Session, material_id: uuid.UUID) -> None:
    """Borrado físico de un material (corrección de errores de alta).

    Solo procede si el material nunca tuvo asignaciones: cualquier fila
    ``AsignacionMaterial`` (activa o histórica) lo referencia por FK
    (``materiales.id`` sin ON DELETE CASCADE) y bloquearía el DELETE. Si hay
    asignaciones se lanza :class:`MaterialEnUso` (→ 409) para preservar el
    histórico; la baja correcta de un material en uso es reportarlo como
    incidencia (CU-24), no borrarlo.
    """

    material = obtener_material(session, material_id)  # 404 si no existe
    asignaciones = repo.count_asignaciones_material(session, material_id)
    if asignaciones:
        raise MaterialEnUso(
            f"el material tiene {asignaciones} asignación(es); no se puede "
            "borrar (repórtalo como incidencia en su lugar)"
        )
    repo.delete_material(session, material)


def eliminar_vehiculo(session: Session, vehiculo_id: uuid.UUID) -> None:
    """Borrado físico de un vehículo (corrección de errores de alta).

    Solo procede si el vehículo nunca tuvo asignaciones: una
    ``AsignacionVehiculo`` (a servicio) o una ``AsignacionMaterial`` de
    dotación lo referencian por FK (``vehiculos.id`` sin ON DELETE CASCADE) y
    bloquearían el DELETE. Si hay asignaciones se lanza
    :class:`VehiculoEnUso` (→ 409); la baja correcta de un vehículo en uso es
    reportarlo como incidencia (CU-24), no borrarlo.
    """

    vehiculo = obtener_vehiculo(session, vehiculo_id)  # 404 si no existe
    asignaciones = repo.count_asignaciones_vehiculo(session, vehiculo_id)
    if asignaciones:
        raise VehiculoEnUso(
            f"el vehículo tiene {asignaciones} asignación(es); no se puede "
            "borrar (repórtalo como incidencia en su lugar)"
        )
    repo.delete_vehiculo(session, vehiculo)


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
    if tipo_asignacion == TipoAsignacion.DOTACION_VEHICULO:
        # Dotación fija a vehículo (PR3): sólo material PRESTABLE.
        if material.tipo != TipoMaterial.PRESTABLE:
            raise TipoAsignacionNoCompatible(
                "dotación de vehículo requiere un material de tipo PRESTABLE"
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
    actor_keycloak_id: str | None = None,
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
    _registrar_evento_voluntario(
        session,
        voluntario_id=voluntario_id,
        tipo_str="asignacion_material",
        payload={
            "material_id": str(material_id),
            "material_nombre": material.nombre,
            "tipo_asignacion": tipo.value,
            "cantidad": cantidad,
            "asignacion_id": str(asignacion.id),
        },
        actor_keycloak_id=actor_keycloak_id,
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
    """CU-22 / US-05-06. Bloqueo por solape de intervalo (PR6 / Política A).

    El material es stock (a diferencia del vehículo, unidad única): el
    chequeo binario "ya hay asignación a servicio" se sustituye por un
    cálculo de unidades disponibles **en el intervalo del servicio
    destino**. Unidades comprometidas en servicios disjuntos no restan;
    sólo las de servicios que solapan ``[inicio, fin)``.

    Además se descuentan las unidades comprometidas fuera de servicio
    (PERSONAL / PRESTAMO / DOTACION_VEHICULO), que son globales (no tienen
    intervalo): una unidad prestada a un voluntario no está disponible para
    ningún servicio, solape o no.

    Reglas de Política A idénticas al vehículo: ``fecha_fin`` NULL no
    evalúa solape de servicio (sólo cuenta el stock global comprometido);
    borrador no reserva (filtro en repo); EMERGENCIA hace override del
    bloqueo por solape (pero el stock físico total sigue siendo un tope
    duro: no se pueden asignar más unidades de las que existen).
    """

    material = obtener_material(session, material_id)
    if material.estado not in (EstadoInventario.OPERATIVO, EstadoInventario.EN_USO):
        raise MaterialNoOperativo(
            f"material en estado {material.estado.value}; no se puede asignar"
        )
    _validar_compatibilidad_tipo(material, TipoAsignacion.SERVICIO)

    servicio = _obtener_servicio(session, servicio_id)
    if servicio.estado == EstadoServicio.CERRADO:
        raise ServicioCerrado(
            f"el servicio {servicio_id} está cerrado; no admite asignaciones"
        )

    # Unidades comprometidas globalmente fuera de servicio (sin intervalo).
    comprometidas_no_servicio = repo.count_unidades_asignadas_material(
        session, material_id, excluir_tipo=TipoAsignacion.SERVICIO
    )

    es_emergencia = servicio.tipo == TipoServicio.EMERGENCIA
    # Unidades reservadas por OTROS servicios que solapan el intervalo
    # destino. Sólo se computan si el destino tiene intervalo cerrado y no
    # es emergencia (regla 2 + regla 4 de Política A).
    reservadas_solapadas = 0
    solapes: list[tuple[Servicio, int]] = []
    if servicio.fecha_fin is not None and not es_emergencia:
        solapes = repo.find_solapes_material(
            session,
            material_id=material_id,
            inicio=servicio.fecha_inicio,
            fin=servicio.fecha_fin,
            excluir_servicio_id=servicio_id,
        )
        reservadas_solapadas = sum(unidades for _, unidades in solapes)

    disponibles = (
        material.cantidad - comprometidas_no_servicio - reservadas_solapadas
    )
    if cantidad > disponibles:
        # Si hay solape concreto, lo señalamos como conflicto (Política A);
        # si el déficit viene sólo del stock global comprometido, es la
        # CantidadInsuficiente clásica.
        if solapes:
            raise MaterialSolapado(
                f"no quedan unidades libres en el intervalo: solicitadas "
                f"{cantidad}, disponibles {max(disponibles, 0)} "
                f"(reservadas por solape {reservadas_solapadas})",
                _conflictos_payload([servicio for servicio, _ in solapes]),
            )
        raise CantidadInsuficiente(
            f"stock insuficiente: solicitadas {cantidad}, "
            f"disponibles para servicio {max(disponibles, 0)}"
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
    actor_keycloak_id: str | None = None,
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

    _registrar_evento_voluntario(
        session,
        voluntario_id=voluntario_id,
        tipo_str="devolucion_material",
        payload={
            "material_id": str(material_id),
            "material_nombre": material.nombre,
            "asignacion_id": str(cerrada.id),
            "observaciones": observaciones,
        },
        actor_keycloak_id=actor_keycloak_id,
    )
    return cerrada


# ---------------------------------------------------------------------------
# Dotación fija de material a vehículo (PR3 / SP-09)
# ---------------------------------------------------------------------------


def asignar_dotacion_vehiculo(
    session: Session,
    *,
    vehiculo_id: uuid.UUID,
    material_id: uuid.UUID,
    cantidad: int = 1,
    cuando: datetime | None = None,
) -> AsignacionMaterial:
    """Asigna material PRESTABLE como dotación fija de un vehículo (PR3).

    Semántica de stock (SP-09): ``Material.cantidad`` es stock **bruto** e
    incluye las unidades dotadas. Una unidad metida en un vehículo no puede
    prestarse a la vez, así que la dotación cuenta como stock consumido en
    los flujos de préstamo a voluntario (``count_unidades_asignadas_material``
    no excluye DOTACION_VEHICULO). La asignación de dotación en sí no se
    valida contra el stock disponible: es una decisión de gestión del
    responsable, no una reserva con tope.

    Reglas:

    - El vehículo debe existir (``VehiculoNoEncontrado`` → 404).
    - El material debe existir (``MaterialNoEncontrado`` → 404) y ser
      PRESTABLE (``TipoAsignacionNoCompatible`` → 409).
    - El material no puede estar en estado final / no operativo
      (``MaterialNoOperativo`` → 409).
    """

    obtener_vehiculo(session, vehiculo_id)  # 404 si no existe
    material = obtener_material(session, material_id)  # 404 si no existe

    if material.estado not in (EstadoInventario.OPERATIVO, EstadoInventario.EN_USO):
        raise MaterialNoOperativo(
            f"material en estado {material.estado.value}; no se puede dotar"
        )
    _validar_compatibilidad_tipo(material, TipoAsignacion.DOTACION_VEHICULO)

    return repo.create_asignacion_material(
        session,
        data=dict(
            material_id=material_id,
            voluntario_id=None,
            servicio_id=None,
            vehiculo_id=vehiculo_id,
            tipo=TipoAsignacion.DOTACION_VEHICULO,
            cantidad=cantidad,
            fecha_asignacion=cuando or datetime.now(),
        ),
    )


def listar_dotacion_vehiculo(
    session: Session, vehiculo_id: uuid.UUID
) -> list[AsignacionMaterial]:
    """Lista la dotación fija activa de un vehículo (PR3)."""

    obtener_vehiculo(session, vehiculo_id)  # 404 si no existe
    return repo.list_dotacion_activa_vehiculo(session, vehiculo_id)


def liberar_dotacion_vehiculo(
    session: Session,
    *,
    vehiculo_id: uuid.UUID,
    asignacion_id: uuid.UUID,
    cuando: datetime | None = None,
) -> AsignacionMaterial:
    """Libera (cierra) una dotación fija de un vehículo (PR3).

    Sella ``fecha_devolucion``; la fila se conserva como histórico. Si la
    dotación no existe, no está activa, no es del vehículo indicado o no
    es de tipo dotación, se lanza ``AsignacionNoEncontrada`` → 404.
    """

    obtener_vehiculo(session, vehiculo_id)  # 404 si no existe

    asignacion = repo.get_dotacion_activa(session, asignacion_id)
    if asignacion is None or asignacion.vehiculo_id != vehiculo_id:
        raise AsignacionNoEncontrada(
            f"no hay dotación activa {asignacion_id} en el vehículo {vehiculo_id}"
        )

    return repo.cerrar_asignacion_material(
        session, asignacion, cuando=cuando or datetime.now()
    )


# ---------------------------------------------------------------------------
# Helper de audit log (EN-02-04 / US-02-06)
# ---------------------------------------------------------------------------


def _registrar_evento_voluntario(
    session: Session,
    *,
    voluntario_id: uuid.UUID,
    tipo_str: str,
    payload: dict | None = None,
    actor_keycloak_id: str | None = None,
) -> None:
    """Audit log con import diferido (mismo patrón en los demás services)."""

    from app.models.voluntario_evento import TipoEventoVoluntario
    from app.repositories import voluntario_evento as eventos_repo

    eventos_repo.registrar(
        session,
        voluntario_id=voluntario_id,
        tipo=TipoEventoVoluntario(tipo_str),
        payload=payload,
        actor_keycloak_id=actor_keycloak_id,
    )


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
    """CU-22 / US-05-07. Bloqueo por solape de intervalo (PR6 / Política A).

    Sustituye el antiguo chequeo binario "ya asignado" por la detección de
    solape temporal contra el resto de servicios que reservan el vehículo en
    el intervalo del servicio destino. Reglas en :data:`Política A`:

    - El servicio destino debe existir (``ServicioNoEncontrado`` → 404).
    - El vehículo debe estar OPERATIVO **o** EN_USO. Un vehículo EN_USO por
      otro servicio sigue siendo asignable a un intervalo disjunto; el estado
      ``EN_USO`` ya no implica indisponibilidad global (eso lo decide el
      solape). Sólo AVERIADO / PERDIDO bloquean por estado.
    - Si el destino tiene ``fecha_fin`` NULL no se evalúa solape (no reserva,
      gestión manual) — se permite siempre que el estado sea sano.
    - Si solapa y el destino NO es EMERGENCIA → ``VehiculoOcupado``.
    - Si el destino es EMERGENCIA → se permite pese al solape (override); no
      se libera la asignación del preventivo (gestión humana).
    """

    vehiculo = obtener_vehiculo(session, vehiculo_id)
    servicio = _obtener_servicio(session, servicio_id)
    if servicio.estado == EstadoServicio.CERRADO:
        raise ServicioCerrado(
            f"el servicio {servicio_id} está cerrado; no admite asignaciones"
        )

    if vehiculo.estado in (EstadoInventario.AVERIADO, EstadoInventario.PERDIDO):
        raise VehiculoNoOperativo(
            f"vehículo en estado {vehiculo.estado.value}; no se puede asignar"
        )

    es_emergencia = servicio.tipo == TipoServicio.EMERGENCIA
    # Sólo se evalúa solape si el destino tiene intervalo cerrado (regla 2)
    # y no es una emergencia (regla 4: override).
    if servicio.fecha_fin is not None and not es_emergencia:
        conflictos = repo.find_servicios_solapados_vehiculo(
            session,
            vehiculo_id=vehiculo_id,
            inicio=servicio.fecha_inicio,
            fin=servicio.fecha_fin,
            excluir_servicio_id=servicio_id,
        )
        if conflictos:
            raise VehiculoOcupado(
                f"el vehículo {vehiculo_id} ya está comprometido en "
                f"{len(conflictos)} servicio(s) que solapan el intervalo",
                _conflictos_payload(conflictos),
            )

    asignacion = repo.create_asignacion_vehiculo(
        session,
        data=dict(
            vehiculo_id=vehiculo_id,
            servicio_id=servicio_id,
            fecha_asignacion=cuando or datetime.now(),
        ),
    )
    # Vehículo único: pasa a EN_USO. Idempotente si ya lo estaba por otra
    # asignación a un intervalo disjunto.
    if vehiculo.estado != EstadoInventario.EN_USO:
        repo.set_estado_vehiculo(
            session, vehiculo, nuevo_estado=EstadoInventario.EN_USO
        )
    return asignacion


def contar_asignaciones_de_servicio(
    session: Session, servicio_id: uuid.UUID
) -> int:
    """Número de asignaciones (material + vehículo) que referencian al
    servicio. Lo usa el borrado de servicios para no dejar FKs huérfanas."""

    return repo.count_asignaciones_servicio(session, servicio_id)


def liberar_y_borrar_asignaciones_de_servicio(
    session: Session, *, servicio_id: uuid.UUID
) -> None:
    """Para el borrado de un servicio: libera los recursos y borra sus filas.

    A diferencia de :func:`liberar_asignaciones_de_servicio` (que se usa al
    CERRAR un servicio y conserva las asignaciones como histórico sellando
    ``fecha_devolucion``), aquí las filas se BORRAN porque el servicio entero
    desaparece. Cada recurso que se quede sin ninguna asignación activa y
    estuviera ``EN_USO`` vuelve a ``OPERATIVO``.

    NO hace commit: forma parte de la transacción única del borrado del
    servicio (un solo commit en :func:`app.services.servicios.eliminar`).
    """

    material_ids, vehiculo_ids = repo.delete_asignaciones_de_servicio(
        session, servicio_id
    )
    # Tras el flush del repo, los recuentos ya no ven las filas borradas.
    for material_id in material_ids:
        material = repo.get_material(session, material_id)
        if material is None or material.estado != EstadoInventario.EN_USO:
            continue
        if repo.count_unidades_asignadas_material(session, material_id) == 0:
            material.estado = EstadoInventario.OPERATIVO
            session.add(material)
    for vehiculo_id in vehiculo_ids:
        vehiculo = repo.get_vehiculo(session, vehiculo_id)
        if vehiculo is None or vehiculo.estado != EstadoInventario.EN_USO:
            continue
        # Un vehículo solo tiene una asignación activa a la vez (regla de
        # negocio): al borrar la del servicio queda libre.
        vehiculo.estado = EstadoInventario.OPERATIVO
        session.add(vehiculo)


# ---------------------------------------------------------------------------
# Lectura del inventario de un servicio (R1 / Opción 1B)
# ---------------------------------------------------------------------------


def listar_inventario_de_servicio(
    session: Session,
    *,
    servicio_id: uuid.UUID,
) -> tuple[list[AsignacionMaterial], list[AsignacionVehiculo]]:
    """Recursos (material + vehículos) asignados a un servicio (R1, lectura).

    Valida que el servicio exista (``ServicioNoEncontrado`` → 404 en el
    router). Devuelve solo asignaciones activas; el nombre del material y
    los identificadores del vehículo viajan precargados (anti-N+1).
    """

    _obtener_servicio(session, servicio_id)
    material = repo.list_inventario_servicio_material(session, servicio_id)
    vehiculos = repo.list_inventario_servicio_vehiculo(session, servicio_id)
    return material, vehiculos


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
