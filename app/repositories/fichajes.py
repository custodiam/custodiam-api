"""Repository del módulo fichajes (EN-04-02)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlmodel import Session, func, select

from app.models.fichaje import Fichaje
from app.models.voluntario import Voluntario


def get(session: Session, fichaje_id: uuid.UUID) -> Fichaje | None:
    return session.get(Fichaje, fichaje_id)


def get_por_servicio_y_voluntario(
    session: Session,
    *,
    servicio_id: uuid.UUID,
    voluntario_id: uuid.UUID,
) -> Fichaje | None:
    """Devuelve el fichaje del par (servicio, voluntario) si existe."""

    stmt = select(Fichaje).where(
        Fichaje.servicio_id == servicio_id,
        Fichaje.voluntario_id == voluntario_id,
    )
    return session.exec(stmt).first()


def list_por_servicio(
    session: Session, servicio_id: uuid.UUID
) -> list[tuple[Voluntario, Fichaje]]:
    """Devuelve (Voluntario, Fichaje) ordenados por hora de entrada (US-04-04)."""

    stmt = (
        select(Voluntario, Fichaje)
        .join(Fichaje, Fichaje.voluntario_id == Voluntario.id)
        .where(Fichaje.servicio_id == servicio_id)
        .order_by(Fichaje.hora_entrada)
    )
    return [(v, f) for v, f in session.exec(stmt).all()]


def list_por_voluntario(
    session: Session, voluntario_id: uuid.UUID
) -> list[Fichaje]:
    """Fichajes históricos de un voluntario (US-04-03)."""

    stmt = (
        select(Fichaje)
        .where(Fichaje.voluntario_id == voluntario_id)
        .order_by(Fichaje.hora_entrada.desc())
    )
    return list(session.exec(stmt).all())


def list_abiertos_por_servicio(
    session: Session, servicio_id: uuid.UUID
) -> list[Fichaje]:
    """Fichajes sin hora_salida en un servicio (US-04-05 auto-cierre)."""

    stmt = select(Fichaje).where(
        Fichaje.servicio_id == servicio_id,
        Fichaje.hora_salida.is_(None),
    )
    return list(session.exec(stmt).all())


def create(session: Session, data: dict[str, Any]) -> Fichaje:
    fichaje = Fichaje(**data)
    session.add(fichaje)
    session.commit()
    session.refresh(fichaje)
    return fichaje


def update(
    session: Session, fichaje: Fichaje, data: dict[str, Any]
) -> Fichaje:
    for key, value in data.items():
        setattr(fichaje, key, value)
    session.add(fichaje)
    session.commit()
    session.refresh(fichaje)
    return fichaje


def delete_por_servicio(session: Session, servicio_id: uuid.UUID) -> int:
    """Borra TODOS los fichajes del servicio.

    Soporta el borrado en cascada del servicio: la FK
    ``fichajes.servicio_id`` no tiene ON DELETE CASCADE, así que hay que
    vaciar los fichajes antes del DELETE del servicio. El PO acepta que el
    borrado de un servicio arrastre sus fichajes (el borrado corrige
    errores de creación). Devuelve el número de filas borradas.

    NO hace commit: el borrado del servicio es una única transacción atómica
    (un solo commit en :func:`app.services.servicios.eliminar`).
    """

    fichajes = list(
        session.exec(
            select(Fichaje).where(Fichaje.servicio_id == servicio_id)
        ).all()
    )
    for fichaje in fichajes:
        session.delete(fichaje)
    session.flush()
    return len(fichajes)


def horas_acumuladas(
    session: Session, voluntario_id: uuid.UUID
) -> tuple[int, int, int]:
    """Devuelve (total_segundos_cerrados, n_cerrados, n_abiertos).

    Solo se computan los fichajes con ``hora_salida`` no nula. Los
    fichajes abiertos se reportan aparte para que el cliente sepa que
    hay tiempo "en curso" que aún no entra en el total acumulado.
    """

    cerrados_stmt = select(
        func.coalesce(
            func.sum(
                func.extract("epoch", Fichaje.hora_salida - Fichaje.hora_entrada)
            ),
            0,
        ),
        func.count(),
    ).where(
        Fichaje.voluntario_id == voluntario_id,
        Fichaje.hora_salida.is_not(None),
    )
    row = session.exec(cerrados_stmt).one()
    total_seg = int(row[0])
    n_cerrados = int(row[1])

    abiertos_stmt = select(func.count()).where(
        Fichaje.voluntario_id == voluntario_id,
        Fichaje.hora_salida.is_(None),
    )
    n_abiertos = int(session.exec(abiertos_stmt).one())
    return total_seg, n_cerrados, n_abiertos


# Re-export para los tests; el valor en sí es opcional.
__all__ = [
    "create",
    "delete_por_servicio",
    "get",
    "get_por_servicio_y_voluntario",
    "horas_acumuladas",
    "list_abiertos_por_servicio",
    "list_por_servicio",
    "list_por_voluntario",
    "update",
]


# Convenience para que datetime esté importado al haberlo declarado en el
# docstring (algunos linters lo marcan como unused si no se referencia).
_ = datetime
