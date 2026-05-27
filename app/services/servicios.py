"""Service del módulo servicios (EN-03-02 + EN-03-03 + EN-03-04).

Orquesta el `Repository` y aplica las reglas de negocio del CU-01
(alta), CU-02 (publicar), CU-03 (convocar), CU-04 (apuntarse /
desapuntarse) y CU-07 (cerrar). La autorización (RBAC declarativo)
vive en el router; este módulo solo refuerza reglas de propiedad
(p. ej. "el voluntario solo se apunta a sí mismo").

Máquina de estados (EN-03-03)
-----------------------------

Transiciones válidas:

    BORRADOR  → PUBLICADO   (publicar)
    BORRADOR  → ACTIVO      (convocar; solo si tipo=EMERGENCIA)
    PUBLICADO → ACTIVO      (convocar)
    ACTIVO    → CERRADO     (cerrar)

Cualquier intento de transición que no aparezca arriba se rechaza con
:class:`TransicionEstadoInvalida`. El router la mapea a HTTP 409
Conflict: el JSON de entrada es válido, lo que está mal es el estado
del servidor; el cliente puede observar `estado` actual y reintentar
tras hacer una transición previa. 422 se reserva para errores de
payload.

Excepciones de dominio
----------------------

- :class:`ServicioNoEncontrado` → 404
- :class:`TransicionEstadoInvalida` → 409
- :class:`YaInscrito` → 409
- :class:`NoInscrito` → 404
- :class:`InscripcionNoPermitidaEnEsteEstado` → 409
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlmodel import Session

from app.models.inscripcion_servicio import InscripcionServicio, TipoInscripcion
from app.models.servicio import EstadoServicio, Servicio, TipoServicio
from app.repositories import servicios as repo

if TYPE_CHECKING:
    from app.models.voluntario import Voluntario
    from app.schemas.servicio import ServicioCreate, ServicioUpdate
    from app.services.fcm_admin import FcmAdminClient
    from app.services.ntfy_client import NtfyClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Excepciones de dominio
# ---------------------------------------------------------------------------


class ServicioError(Exception):
    """Base de las excepciones de dominio del módulo servicios."""


class ServicioNoEncontrado(ServicioError):  # noqa: N818 — castellano
    """No existe un servicio con el identificador pedido."""


class TransicionEstadoInvalida(ServicioError):  # noqa: N818 — castellano
    """La transición de estado solicitada no es válida para este servicio.

    Lleva el estado actual y el solicitado para que el router pueda
    formar un mensaje descriptivo sin tocar la lógica de transiciones.
    """

    def __init__(
        self,
        actual: EstadoServicio,
        solicitado: EstadoServicio,
        motivo: str | None = None,
    ) -> None:
        self.actual = actual
        self.solicitado = solicitado
        self.motivo = motivo
        partes = [
            f"transición {actual.value!r} → {solicitado.value!r} no permitida"
        ]
        if motivo:
            partes.append(motivo)
        super().__init__(": ".join(partes))


class YaInscrito(ServicioError):  # noqa: N818 — castellano
    """El voluntario ya tiene una inscripción activa en el servicio."""


class NoInscrito(ServicioError):  # noqa: N818 — castellano
    """El voluntario no tenía inscripción en este servicio."""


class InscripcionNoPermitidaEnEsteEstado(ServicioError):  # noqa: N818
    """El servicio no admite inscripciones en su estado actual."""


# ---------------------------------------------------------------------------
# Tabla de transiciones válidas
# ---------------------------------------------------------------------------


# Estados destino permitidos desde cada estado origen, sin contar la
# condición especial BORRADOR→ACTIVO que solo es válida para emergencias
# (se evalúa por separado en `_validar_transicion`).
_TRANSICIONES_BASE: dict[EstadoServicio, set[EstadoServicio]] = {
    EstadoServicio.BORRADOR: {EstadoServicio.PUBLICADO},
    EstadoServicio.PUBLICADO: {EstadoServicio.ACTIVO},
    EstadoServicio.ACTIVO: {EstadoServicio.CERRADO},
    EstadoServicio.CERRADO: set(),
}


def _validar_transicion(
    actual: EstadoServicio,
    solicitado: EstadoServicio,
    tipo: TipoServicio,
) -> None:
    if solicitado in _TRANSICIONES_BASE[actual]:
        return
    # Atajo de emergencia: BORRADOR → ACTIVO solo si es emergencia.
    if (
        actual == EstadoServicio.BORRADOR
        and solicitado == EstadoServicio.ACTIVO
        and tipo == TipoServicio.EMERGENCIA
    ):
        return
    raise TransicionEstadoInvalida(actual, solicitado)


# ---------------------------------------------------------------------------
# Lecturas
# ---------------------------------------------------------------------------


def listar(
    session: Session,
    *,
    skip: int = 0,
    limit: int = 50,
    q: str | None = None,
    estado: EstadoServicio | None = None,
    tipo: TipoServicio | None = None,
) -> tuple[list[Servicio], int]:
    return repo.list_paginated(
        session, skip=skip, limit=limit, q=q, estado=estado, tipo=tipo
    )


def obtener(session: Session, servicio_id: uuid.UUID) -> Servicio:
    servicio = repo.get_full(session, servicio_id)
    if servicio is None:
        raise ServicioNoEncontrado(str(servicio_id))
    return servicio


def listar_voluntarios(
    session: Session, servicio_id: uuid.UUID
) -> list[tuple[Voluntario, InscripcionServicio]]:
    """Lista (Voluntario, Inscripcion) para `GET /servicios/{id}/voluntarios`."""

    obtener(session, servicio_id)  # 404 si no existe
    return repo.list_voluntarios_por_servicio(session, servicio_id)


# ---------------------------------------------------------------------------
# Escrituras del propio servicio
# ---------------------------------------------------------------------------


def crear(
    session: Session,
    data: ServicioCreate,
    *,
    creado_por_keycloak_id: str | None = None,
) -> Servicio:
    """Alta de servicio (CU-01).

    El estado inicial depende del tipo:

    - ``emergencia`` → ``activo`` directamente (CU-01 flujo alternativo).
    - resto → ``borrador``.

    Mantener esta decisión en el service permite que el router se
    despreocupe del estado inicial y simplifica los tests.
    """

    payload = data.model_dump(exclude_unset=False)
    payload["estado"] = (
        EstadoServicio.ACTIVO
        if data.tipo == TipoServicio.EMERGENCIA
        else EstadoServicio.BORRADOR
    )
    payload["creado_por_keycloak_id"] = creado_por_keycloak_id
    return repo.create(session, payload)


def actualizar(
    session: Session,
    servicio_id: uuid.UUID,
    data: ServicioUpdate,
) -> Servicio:
    """PATCH de campos editables. NO cambia ``estado`` (eso va por su endpoint)."""

    servicio = repo.get(session, servicio_id)
    if servicio is None:
        raise ServicioNoEncontrado(str(servicio_id))
    patch = data.model_dump(exclude_unset=True)
    return repo.update(session, servicio, patch)


def publicar(session: Session, servicio_id: uuid.UUID) -> Servicio:
    """CU-02. Pone el servicio en estado PUBLICADO."""

    servicio = repo.get(session, servicio_id)
    if servicio is None:
        raise ServicioNoEncontrado(str(servicio_id))
    _validar_transicion(servicio.estado, EstadoServicio.PUBLICADO, servicio.tipo)
    return repo.set_estado(session, servicio, nuevo_estado=EstadoServicio.PUBLICADO)


def convocar(
    session: Session,
    servicio_id: uuid.UUID,
    *,
    voluntario_ids: list[uuid.UUID] | None = None,
    fecha: datetime | None = None,
    fcm_client: FcmAdminClient | None = None,
    ntfy_client: NtfyClient | None = None,
) -> tuple[Servicio, list[InscripcionServicio]]:
    """CU-03. Convoca voluntarios y pasa el servicio a ACTIVO.

    Si ``voluntario_ids`` es ``None`` o vacío, convoca a todos los
    voluntarios activos (US-03-04). Si trae ids concretos, solo esos
    (US-03-05 / US-03-06).

    Si ``fcm_client`` o ``ntfy_client`` están presentes (Epic E06), tras
    materializar las inscripciones se dispara el fan-out de
    notificaciones push (FCM) y, para emergencias, también el canal
    redundante ntfy. La importación de ``app.services.notificaciones``
    se hace dentro de la función para evitar dependencia circular entre
    módulos service.
    """

    servicio = repo.get(session, servicio_id)
    if servicio is None:
        raise ServicioNoEncontrado(str(servicio_id))

    # Si el servicio no está ya activo, intentamos la transición.
    if servicio.estado != EstadoServicio.ACTIVO:
        _validar_transicion(servicio.estado, EstadoServicio.ACTIVO, servicio.tipo)
        repo.set_estado(session, servicio, nuevo_estado=EstadoServicio.ACTIVO)

    # Resolver el universo de convocados.
    ids: list[uuid.UUID]
    if voluntario_ids:
        ids = list(voluntario_ids)
    else:
        ids = repo.list_ids_voluntarios_activos(session)

    cuando = fecha or datetime.now()
    inscripciones = [
        repo.upsert_inscripcion(
            session,
            servicio_id=servicio.id,
            voluntario_id=vol_id,
            tipo=TipoInscripcion.CONVOCADO,
            fecha=cuando,
        )
        for vol_id in ids
    ]

    if fcm_client is not None or ntfy_client is not None:
        from app.services import notificaciones as notificaciones_service

        try:
            notificaciones_service.notificar_convocatoria(
                session,
                servicio=servicio,
                voluntario_ids=ids,
                fcm_client=fcm_client,
                ntfy_client=ntfy_client,
            )
        except Exception:
            # Defensa de último nivel: una caída inesperada en el
            # subsistema de notificaciones nunca debe romper la
            # convocatoria del servicio en BD. Los errores conocidos
            # (FcmAdminError, NtfyError) ya los maneja el propio
            # service de notificaciones; aquí cubrimos lo imprevisto.
            logger.exception(
                "fallo inesperado notificando convocatoria del servicio %s",
                servicio.id,
            )

    return servicio, inscripciones


def cerrar(
    session: Session,
    servicio_id: uuid.UUID,
    *,
    observaciones: str | None = None,
    fecha_cierre: datetime | None = None,
) -> Servicio:
    """CU-07. Pone el servicio en CERRADO.

    Antes de marcar el cierre se cierran automáticamente los fichajes
    abiertos de los voluntarios que no han fichado salida (US-04-05).
    La importación de ``app.services.fichajes`` se hace dentro de la
    función para evitar dependencia circular entre módulos service.
    """

    servicio = repo.get(session, servicio_id)
    if servicio is None:
        raise ServicioNoEncontrado(str(servicio_id))
    _validar_transicion(servicio.estado, EstadoServicio.CERRADO, servicio.tipo)

    cuando_cierre = fecha_cierre or datetime.now()

    # US-04-05: fichaje automático antes de cambiar el estado para que el
    # voluntario sepa que su salida quedó sellada con la hora del cierre.
    from app.services import fichajes as fichajes_service

    fichajes_service.cerrar_fichajes_abiertos(
        session, servicio_id=servicio.id, cuando=cuando_cierre
    )

    # US-05-06 / US-05-07: liberación automática de material y vehículos
    # asignados al servicio. Mismo patrón cross-feature que el fichaje
    # (import dentro de la función para evitar circular).
    from app.services import inventario as inventario_service

    inventario_service.liberar_asignaciones_de_servicio(
        session, servicio_id=servicio.id, cuando=cuando_cierre
    )

    return repo.set_estado(
        session,
        servicio,
        nuevo_estado=EstadoServicio.CERRADO,
        fecha_cierre=cuando_cierre,
        observaciones_cierre=observaciones,
    )


# ---------------------------------------------------------------------------
# Self-service de inscripciones (CU-04 / EN-03-04)
# ---------------------------------------------------------------------------


def _servicio_admite_inscripcion(estado: EstadoServicio) -> bool:
    """Un voluntario puede apuntarse mientras el servicio acepta inscripciones.

    Acepta inscripciones en ``publicado`` (CU-04 stricto) y también en
    ``activo`` (un voluntario aún no inscrito puede unirse al servicio
    en marcha, p. ej. una emergencia que ya activó pero a la que el
    voluntario se suma autónomamente). Rechaza en ``borrador`` (no
    visible) y en ``cerrado`` (final).
    """

    return estado in (EstadoServicio.PUBLICADO, EstadoServicio.ACTIVO)


def apuntarse_propio(
    session: Session,
    *,
    servicio_id: uuid.UUID,
    voluntario_id: uuid.UUID,
    fecha: datetime | None = None,
) -> InscripcionServicio:
    """CU-04. El voluntario se apunta a sí mismo a un servicio publicado."""

    servicio = repo.get(session, servicio_id)
    if servicio is None:
        raise ServicioNoEncontrado(str(servicio_id))
    if not _servicio_admite_inscripcion(servicio.estado):
        raise InscripcionNoPermitidaEnEsteEstado(
            f"estado={servicio.estado.value}"
        )

    existente = repo.get_inscripcion(
        session, servicio_id=servicio_id, voluntario_id=voluntario_id
    )
    if existente is not None:
        raise YaInscrito(str(servicio_id))

    return repo.upsert_inscripcion(
        session,
        servicio_id=servicio_id,
        voluntario_id=voluntario_id,
        tipo=TipoInscripcion.INSCRITO,
        fecha=fecha or datetime.now(),
    )


def desapuntarse_propio(
    session: Session,
    *,
    servicio_id: uuid.UUID,
    voluntario_id: uuid.UUID,
) -> None:
    """CU-04 alternativo A. El voluntario se da de baja del servicio.

    Solo está permitido para inscripciones de tipo ``INSCRITO`` (las
    convocatorias hechas por un mando no pueden cancelarse por el
    propio voluntario — eso requeriría una decisión adicional fuera
    del scope de E03).
    """

    inscripcion = repo.get_inscripcion(
        session, servicio_id=servicio_id, voluntario_id=voluntario_id
    )
    if inscripcion is None:
        raise NoInscrito(str(servicio_id))
    if inscripcion.tipo != TipoInscripcion.INSCRITO:
        raise InscripcionNoPermitidaEnEsteEstado(
            "no se puede cancelar una convocatoria desde el propio voluntario"
        )
    repo.delete_inscripcion(session, inscripcion)
