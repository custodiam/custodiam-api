"""Repository del módulo disponibilidad (US-02-04 / CU-12).

Concentra las queries SQLModel sobre :class:`Disponibilidad`. El Service
llama a este módulo; el Router NUNCA lo importa directamente.

Las funciones aquí son puras desde el punto de vista de negocio: no
validan permisos, no resuelven el voluntario desde el JWT y no rechazan
fechas pasadas. Esa lógica vive en :mod:`app.services.disponibilidad`.
"""

from __future__ import annotations

import calendar
import uuid
from datetime import date

from sqlmodel import Session, select

from app.models.disponibilidad import Disponibilidad


def get_by_voluntario_y_fecha(
    session: Session,
    *,
    voluntario_id: uuid.UUID,
    fecha: date,
) -> Disponibilidad | None:
    """Devuelve la fila del par (voluntario, fecha) si existe.

    La UNIQUE constraint sobre ``(voluntario_id, fecha)`` garantiza que
    como mucho hay una; se aprovecha para el camino del UPSERT.
    """

    stmt = select(Disponibilidad).where(
        Disponibilidad.voluntario_id == voluntario_id,
        Disponibilidad.fecha == fecha,
    )
    return session.exec(stmt).first()


def list_by_voluntario_mes(
    session: Session,
    *,
    voluntario_id: uuid.UUID,
    year: int,
    month: int,
) -> list[Disponibilidad]:
    """Devuelve las filas del voluntario para el mes (year, month).

    El rango es ``[primer_dia_del_mes, ultimo_dia_del_mes]`` inclusive.
    ``calendar.monthrange`` resuelve el último día sin dependencias
    externas y maneja años bisiestos correctamente.
    """

    primer_dia = date(year, month, 1)
    ultimo_dia = date(year, month, calendar.monthrange(year, month)[1])
    stmt = (
        select(Disponibilidad)
        .where(
            Disponibilidad.voluntario_id == voluntario_id,
            Disponibilidad.fecha >= primer_dia,
            Disponibilidad.fecha <= ultimo_dia,
        )
        .order_by(Disponibilidad.fecha)
    )
    return list(session.exec(stmt).all())


def upsert_dia(
    session: Session,
    *,
    voluntario_id: uuid.UUID,
    fecha: date,
    disponible: bool,
) -> Disponibilidad:
    """Crea o actualiza la fila del par (voluntario, fecha).

    Idempotente: el comportamiento esperado por el flujo del calendario
    (tap toggle) — el cliente envía el nuevo estado y el backend lo
    persiste sin importar el estado previo. Si la fila no existe se
    inserta; si existe, solo se actualiza el flag ``disponible``.
    """

    existente = get_by_voluntario_y_fecha(
        session, voluntario_id=voluntario_id, fecha=fecha
    )
    if existente is not None:
        existente.disponible = disponible
        session.add(existente)
        session.commit()
        session.refresh(existente)
        return existente

    nueva = Disponibilidad(
        voluntario_id=voluntario_id,
        fecha=fecha,
        disponible=disponible,
    )
    session.add(nueva)
    session.commit()
    session.refresh(nueva)
    return nueva
