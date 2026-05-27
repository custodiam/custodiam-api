"""Repository del módulo dispositivos / notificaciones (Epic E06).

Concentra todas las queries SQLModel sobre ``Dispositivo`` y
``Notificacion``. El Service llama a este módulo; el Router NUNCA lo
importa directamente.

Las funciones aquí son puras desde el punto de vista de negocio: no
validan permisos, no resuelven el voluntario desde el JWT y no lanzan
HTTPException. Se limitan a leer y escribir filas.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence

from sqlmodel import Session, select

from app.models.dispositivo import Dispositivo, PlataformaDispositivo
from app.models.notificacion import (
    Notificacion,
    PrioridadNotificacion,
    TipoNotificacion,
)


# ---------------------------------------------------------------------------
# Dispositivos
# ---------------------------------------------------------------------------


def get(session: Session, dispositivo_id: uuid.UUID) -> Dispositivo | None:
    """Devuelve el dispositivo por PK, sin importar si está activo."""

    return session.get(Dispositivo, dispositivo_id)


def get_by_fcm_token(
    session: Session, fcm_token: str
) -> Dispositivo | None:
    """Busca un dispositivo por su ``fcm_token`` (UNIQUE)."""

    stmt = select(Dispositivo).where(Dispositivo.fcm_token == fcm_token)
    return session.exec(stmt).first()


def list_activos_por_voluntario(
    session: Session, voluntario_id: uuid.UUID
) -> list[Dispositivo]:
    """Devuelve los dispositivos ``activo=True`` de un voluntario."""

    stmt = (
        select(Dispositivo)
        .where(
            Dispositivo.voluntario_id == voluntario_id,
            Dispositivo.activo.is_(True),
        )
        .order_by(Dispositivo.ultima_actualizacion.desc())
    )
    return list(session.exec(stmt).all())


def list_tokens_activos_de_voluntarios(
    session: Session, voluntario_ids: Sequence[uuid.UUID]
) -> list[Dispositivo]:
    """Devuelve los dispositivos activos del conjunto de voluntarios dado.

    Pensado para el fan-out de notificaciones desde ``servicios.convocar``:
    recibe la lista de voluntarios convocados y devuelve todos sus
    dispositivos ``activo=True`` en un solo round-trip.
    """

    if not voluntario_ids:
        return []
    stmt = select(Dispositivo).where(
        Dispositivo.voluntario_id.in_(list(voluntario_ids)),
        Dispositivo.activo.is_(True),
    )
    return list(session.exec(stmt).all())


def upsert(
    session: Session,
    *,
    voluntario_id: uuid.UUID,
    fcm_token: str,
    plataforma: PlataformaDispositivo,
) -> Dispositivo:
    """Registro idempotente de un token FCM (US-06-04).

    Comportamiento:

    - Si el token no existe, crea una fila nueva con ``activo=True``.
    - Si el token ya existe vinculado al mismo voluntario, actualiza la
      plataforma (rara vez cambia, pero un Web que pasa a PWA en Android
      podría) y reactiva el flag ``activo`` si estaba en ``False``.
    - Si el token ya existe vinculado a OTRO voluntario, reasigna la fila
      al nuevo voluntario y la mantiene activa. Esto cubre el flujo
      "el dispositivo cambió de usuario" sin generar tokens duplicados
      en la BD ni violar la UNIQUE en ``fcm_token``.
    """

    existente = get_by_fcm_token(session, fcm_token)
    if existente is not None:
        existente.voluntario_id = voluntario_id
        existente.plataforma = plataforma
        existente.activo = True
        session.add(existente)
        session.commit()
        session.refresh(existente)
        return existente

    nuevo = Dispositivo(
        voluntario_id=voluntario_id,
        fcm_token=fcm_token,
        plataforma=plataforma,
        activo=True,
    )
    session.add(nuevo)
    session.commit()
    session.refresh(nuevo)
    return nuevo


def desactivar(session: Session, dispositivo: Dispositivo) -> Dispositivo:
    """Soft delete: marca el dispositivo como inactivo sin borrar la fila."""

    dispositivo.activo = False
    session.add(dispositivo)
    session.commit()
    session.refresh(dispositivo)
    return dispositivo


# ---------------------------------------------------------------------------
# Notificaciones (audit log)
# ---------------------------------------------------------------------------


def crear_notificacion(
    session: Session,
    *,
    tipo: TipoNotificacion,
    prioridad: PrioridadNotificacion,
    titulo: str,
    cuerpo: str,
    servicio_id: uuid.UUID | None = None,
    enviadas_count: int = 0,
    entregadas_count: int = 0,
) -> Notificacion:
    """Inserta una fila en el audit log de notificaciones."""

    notif = Notificacion(
        tipo=tipo,
        prioridad=prioridad,
        titulo=titulo,
        cuerpo=cuerpo,
        servicio_id=servicio_id,
        enviadas_count=enviadas_count,
        entregadas_count=entregadas_count,
    )
    session.add(notif)
    session.commit()
    session.refresh(notif)
    return notif


def list_tokens_planos(dispositivos: Iterable[Dispositivo]) -> list[str]:
    """Helper puro: extrae los ``fcm_token`` de una colección de dispositivos."""

    return [d.fcm_token for d in dispositivos]
