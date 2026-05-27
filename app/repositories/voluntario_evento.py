"""Repository del módulo voluntario_evento (EN-02-04 / US-02-06).

Concentra las queries SQLModel sobre :class:`VoluntarioEvento` y los
agregados del resumen del voluntario (horas + servicios + último
servicio). El Service llama a este módulo; el Router NUNCA lo importa.

Decisiones:

- ``registrar()`` hace ``commit`` de la fila por separado del flujo
  llamante. Aceptamos el coste de un commit adicional por evento a
  cambio de la garantía de durabilidad: si la transacción operativa
  (p. ej. crear inscripción) tiene éxito, el evento queda persistido
  inmediatamente y no depende de un commit posterior.
- ``list_by_voluntario`` devuelve ``(items, total)`` para soportar
  ``X-Total-Count`` sin emitir un HEAD adicional desde el cliente.
- Los filtros opcionales (``tipos``, ``since``, ``until``) se aplican
  en SQL para no traer filas innecesarias.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlmodel import Session, func, select

from app.models.inscripcion_servicio import InscripcionServicio
from app.models.servicio import EstadoServicio, Servicio
from app.models.voluntario_evento import TipoEventoVoluntario, VoluntarioEvento

# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def registrar(
    session: Session,
    *,
    voluntario_id: uuid.UUID,
    tipo: TipoEventoVoluntario,
    payload: dict[str, Any] | None = None,
    actor_keycloak_id: str | None = None,
) -> VoluntarioEvento:
    """Inserta una fila en el audit log y la commitea."""

    evento = VoluntarioEvento(
        voluntario_id=voluntario_id,
        tipo_evento=tipo,
        payload=payload,
        actor_keycloak_id=actor_keycloak_id,
    )
    session.add(evento)
    session.commit()
    session.refresh(evento)
    return evento


def list_by_voluntario(
    session: Session,
    *,
    voluntario_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
    tipos: Sequence[TipoEventoVoluntario] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> tuple[list[VoluntarioEvento], int]:
    """Lista paginada del histórico del voluntario, más reciente primero."""

    base = select(VoluntarioEvento).where(
        VoluntarioEvento.voluntario_id == voluntario_id
    )
    if tipos:
        base = base.where(VoluntarioEvento.tipo_evento.in_(list(tipos)))
    if since is not None:
        base = base.where(VoluntarioEvento.created_at >= since)
    if until is not None:
        base = base.where(VoluntarioEvento.created_at <= until)

    total_stmt = select(func.count()).select_from(base.subquery())
    total = session.exec(total_stmt).one()

    items_stmt = (
        base.order_by(VoluntarioEvento.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    items = list(session.exec(items_stmt).all())
    return items, int(total)


# ---------------------------------------------------------------------------
# Agregados para el resumen (CU-13)
# ---------------------------------------------------------------------------


def count_servicios_cerrados_participados(
    session: Session, voluntario_id: uuid.UUID
) -> int:
    """Número de servicios CERRADOS en los que el voluntario participó.

    Un servicio "participado" es aquel donde existe una inscripción del
    voluntario (sea ``INSCRITO`` o ``CONVOCADO``) y cuyo estado actual
    es ``cerrado``. Servicios en cualquier otro estado se ignoran
    porque aún no han concluido: contar servicios en curso o publicados
    daría una cifra que no refleja la participación real del voluntario.
    """

    stmt = (
        select(func.count())
        .select_from(InscripcionServicio)
        .join(Servicio, Servicio.id == InscripcionServicio.servicio_id)
        .where(
            InscripcionServicio.voluntario_id == voluntario_id,
            Servicio.estado == EstadoServicio.CERRADO,
        )
    )
    return int(session.exec(stmt).one())


def ultimo_servicio_participado(
    session: Session, voluntario_id: uuid.UUID
) -> Servicio | None:
    """Devuelve el servicio cerrado más reciente en el que participó."""

    stmt = (
        select(Servicio)
        .join(InscripcionServicio, InscripcionServicio.servicio_id == Servicio.id)
        .where(
            InscripcionServicio.voluntario_id == voluntario_id,
            Servicio.estado == EstadoServicio.CERRADO,
        )
        .order_by(Servicio.fecha_inicio.desc())
        .limit(1)
    )
    return session.exec(stmt).first()
