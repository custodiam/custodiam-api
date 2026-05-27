"""Service del módulo notificaciones (Epic E06).

Orquesta el envío redundante FCM + ntfy y deja constancia en el audit
log (:class:`Notificacion`). El consumidor primario es
``app.services.servicios.convocar``, que tras crear las inscripciones
disparadas por un mando llama a :func:`notificar_convocatoria` para
notificar a los voluntarios convocados.

Reglas de resiliencia
---------------------

- Los errores de envío (:class:`FcmAdminError`, :class:`NtfyError`) se
  registran en log pero **no** se propagan: una notificación fallida
  no debe romper la convocatoria del servicio en BD.
- Si FCM devuelve ``False`` para un token (token desregistrado o
  inválido), el dispositivo se marca como ``activo=False`` para no
  reintentar en la siguiente convocatoria.
- El audit log siempre se persiste, incluso si todos los envíos fallan
  (ofrece trazabilidad: "se intentó notificar X a Y voluntarios").
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence

from sqlmodel import Session

from app.models.notificacion import (
    Notificacion,
    PrioridadNotificacion,
    TipoNotificacion,
)
from app.models.servicio import Servicio, TipoServicio
from app.repositories import dispositivos as repo
from app.services.fcm_admin import FcmAdminClient, FcmAdminError
from app.services.ntfy_client import NtfyClient, NtfyError

logger = logging.getLogger(__name__)


# Topic de ntfy reservado a emergencias. El topic se elige aquí para que
# el caller no necesite conocer el detalle de ntfy.
_NTFY_TOPIC_EMERGENCIAS = "custodiam-emergencias"


def _clasificar_servicio(
    servicio: Servicio,
) -> tuple[TipoNotificacion, PrioridadNotificacion]:
    """Decide ``(tipo, prioridad)`` de la notificación según el servicio.

    - ``EMERGENCIA`` → notificación crítica para todos los destinatarios.
    - ``PREVENTIVO`` y ``OTRO`` → notificación normal.
    - ``FORMACION`` → notificación de baja prioridad (no urgente).
    """

    if servicio.tipo == TipoServicio.EMERGENCIA:
        return TipoNotificacion.EMERGENCIA, PrioridadNotificacion.CRITICA
    if servicio.tipo == TipoServicio.FORMACION:
        return TipoNotificacion.SERVICIO, PrioridadNotificacion.BAJA
    return TipoNotificacion.SERVICIO, PrioridadNotificacion.NORMAL


def _formatear_titulo_y_cuerpo(
    servicio: Servicio,
    tipo: TipoNotificacion,
) -> tuple[str, str]:
    """Construye el título y el cuerpo del push.

    Formato para emergencias siguiendo el criterio de aceptación de
    US-06-01 (sin emojis en el modelo, los pinta el cliente al
    renderizar). Para el resto, formato compacto con título y fecha.
    """

    if tipo == TipoNotificacion.EMERGENCIA:
        titulo = f"EMERGENCIA: {servicio.titulo}"
        cuerpo = (
            f"Ubicación: {servicio.ubicacion}. "
            f"Inicio: {servicio.fecha_inicio.isoformat(timespec='minutes')}."
        )
        return titulo, cuerpo

    titulo = "Nuevo servicio disponible"
    cuerpo = (
        f"{servicio.titulo} — "
        f"{servicio.fecha_inicio.isoformat(timespec='minutes')}"
    )
    return titulo, cuerpo


def notificar_convocatoria(
    session: Session,
    *,
    servicio: Servicio,
    voluntario_ids: Sequence[uuid.UUID],
    fcm_client: FcmAdminClient | None = None,
    ntfy_client: NtfyClient | None = None,
) -> Notificacion:
    """Lanza el fan-out de notificaciones por la convocatoria de un servicio.

    Persiste el audit log incluso si todos los envíos fallan o si ambos
    clientes están deshabilitados — la fila ``Notificacion`` con
    ``enviadas_count=0`` documenta el intento.
    """

    tipo, prioridad = _clasificar_servicio(servicio)
    titulo, cuerpo = _formatear_titulo_y_cuerpo(servicio, tipo)
    data_push = {"servicio_id": str(servicio.id), "tipo": tipo.value}

    enviadas_fcm = _fan_out_fcm(
        session,
        voluntario_ids=voluntario_ids,
        fcm_client=fcm_client,
        titulo=titulo,
        cuerpo=cuerpo,
        prioridad=prioridad,
        data=data_push,
    )

    enviadas_ntfy = _ntfy_para_emergencias(
        ntfy_client=ntfy_client,
        tipo=tipo,
        prioridad=prioridad,
        titulo=titulo,
        cuerpo=cuerpo,
    )

    return repo.crear_notificacion(
        session,
        tipo=tipo,
        prioridad=prioridad,
        titulo=titulo,
        cuerpo=cuerpo,
        servicio_id=servicio.id,
        enviadas_count=enviadas_fcm + enviadas_ntfy,
    )


def _fan_out_fcm(
    session: Session,
    *,
    voluntario_ids: Sequence[uuid.UUID],
    fcm_client: FcmAdminClient | None,
    titulo: str,
    cuerpo: str,
    prioridad: PrioridadNotificacion,
    data: dict[str, str],
) -> int:
    """Recolecta tokens FCM y envía un push por cada uno. Devuelve cuántos OK.

    - Si ``fcm_client`` está deshabilitado (o es ``None``), no se hace
      ninguna request y se devuelve 0.
    - Tokens marcados como inválidos por FCM se desactivan en BD para
      no volver a intentarlo en convocatorias futuras.
    - Errores transitorios (5xx, red) se registran en log y la siguiente
      iteración continúa: una caída parcial de FCM no debe parar el
      fan-out completo.
    """

    if fcm_client is None or not fcm_client.enabled:
        return 0

    dispositivos = repo.list_tokens_activos_de_voluntarios(
        session, voluntario_ids
    )
    enviadas = 0
    for dispositivo in dispositivos:
        try:
            resultado = fcm_client.enviar(
                token=dispositivo.fcm_token,
                titulo=titulo,
                cuerpo=cuerpo,
                prioridad=prioridad,
                data=data,
            )
        except FcmAdminError:
            logger.exception(
                "fallo transitorio enviando push FCM al dispositivo %s",
                dispositivo.id,
            )
            continue

        if resultado is True:
            enviadas += 1
            continue
        if resultado is False:
            # Token caducado o desregistrado: bajar el dispositivo.
            repo.desactivar(session, dispositivo)
    return enviadas


def _ntfy_para_emergencias(
    *,
    ntfy_client: NtfyClient | None,
    tipo: TipoNotificacion,
    prioridad: PrioridadNotificacion,
    titulo: str,
    cuerpo: str,
) -> int:
    """Publica en ntfy solo para emergencias. Devuelve 1 si tuvo éxito.

    El canal ntfy se usa exclusivamente como redundancia para
    emergencias, no para servicios normales: un voluntario suscrito al
    topic de emergencias espera oírlo solo cuando hay emergencia.
    """

    if (
        ntfy_client is None
        or not ntfy_client.enabled
        or tipo != TipoNotificacion.EMERGENCIA
    ):
        return 0

    try:
        ok = ntfy_client.enviar(
            titulo=titulo,
            cuerpo=cuerpo,
            prioridad=prioridad,
            topic=_NTFY_TOPIC_EMERGENCIAS,
            tags=["emergencia", "rotating_light"],
        )
    except NtfyError:
        logger.exception("fallo publicando emergencia en ntfy")
        return 0
    return 1 if ok else 0
