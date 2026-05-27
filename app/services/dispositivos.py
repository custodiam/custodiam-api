"""Service del módulo dispositivos (Epic E06).

Orquesta el :mod:`app.repositories.dispositivos` y aplica las reglas de
negocio del registro idempotente de tokens FCM (US-06-04) y de la
auto-baja por el propio voluntario.

Excepciones de dominio
----------------------

- :class:`DispositivoNoEncontrado` → 404
- :class:`DispositivoDeOtroVoluntario` → 403
"""

from __future__ import annotations

import uuid

from sqlmodel import Session

from app.models.dispositivo import Dispositivo, PlataformaDispositivo
from app.repositories import dispositivos as repo


class DispositivoError(Exception):
    """Base de las excepciones de dominio del módulo dispositivos."""


class DispositivoNoEncontrado(DispositivoError):  # noqa: N818 — castellano
    """No existe un dispositivo con el identificador pedido."""


class DispositivoDeOtroVoluntario(DispositivoError):  # noqa: N818 — castellano
    """El dispositivo pertenece a otro voluntario; el actual no puede operarlo."""


def registrar(
    session: Session,
    *,
    voluntario_id: uuid.UUID,
    fcm_token: str,
    plataforma: PlataformaDispositivo,
) -> Dispositivo:
    """Registra (o refresca) el token FCM del voluntario actual.

    Delegado a ``repo.upsert``, que implementa la semántica idempotente
    descrita en US-06-04: el mismo token siempre vive en una única fila
    de la tabla; si cambia de dueño, la fila se reasigna; si estaba
    inactivo, se reactiva.
    """

    return repo.upsert(
        session,
        voluntario_id=voluntario_id,
        fcm_token=fcm_token,
        plataforma=plataforma,
    )


def listar_propios(
    session: Session, voluntario_id: uuid.UUID
) -> list[Dispositivo]:
    """Devuelve los dispositivos activos del voluntario actual."""

    return repo.list_activos_por_voluntario(session, voluntario_id)


def dar_baja_propio(
    session: Session,
    *,
    dispositivo_id: uuid.UUID,
    voluntario_id_actual: uuid.UUID,
) -> Dispositivo:
    """Soft delete del dispositivo, comprobando que pertenece al voluntario.

    La comprobación de propiedad vive en el Service (no en el repo) para
    devolver 403 — no 404 — cuando el id existe pero pertenece a otro
    voluntario. Mismo patrón que ``servicios.desapuntarse_propio``.
    """

    dispositivo = repo.get(session, dispositivo_id)
    if dispositivo is None:
        raise DispositivoNoEncontrado(str(dispositivo_id))
    if dispositivo.voluntario_id != voluntario_id_actual:
        raise DispositivoDeOtroVoluntario(str(dispositivo_id))
    return repo.desactivar(session, dispositivo)
