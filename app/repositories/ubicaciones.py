"""Repository del catálogo de ubicaciones (E10 / PR2)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlmodel import Session, func, select

from app.models.ubicacion import Ubicacion


def get_ubicacion(session: Session, ubicacion_id: uuid.UUID) -> Ubicacion | None:
    return session.get(Ubicacion, ubicacion_id)


def get_ubicacion_por_nombre(session: Session, nombre: str) -> Ubicacion | None:
    stmt = select(Ubicacion).where(Ubicacion.nombre == nombre)
    return session.exec(stmt).first()


def list_ubicaciones(
    session: Session,
    *,
    skip: int = 0,
    limit: int = 50,
    q: str | None = None,
) -> tuple[list[Ubicacion], int]:
    """Lista paginada con búsqueda por nombre (US-05-12, alimenta el picker)."""

    base = select(Ubicacion)
    if q:
        base = base.where(Ubicacion.nombre.ilike(f"%{q}%"))

    total_stmt = select(func.count()).select_from(base.subquery())
    total = int(session.exec(total_stmt).one())

    items_stmt = base.order_by(Ubicacion.nombre).offset(skip).limit(limit)
    items = list(session.exec(items_stmt).all())
    return items, total


def create_ubicacion(session: Session, data: dict[str, Any]) -> Ubicacion:
    ubicacion = Ubicacion(**data)
    session.add(ubicacion)
    session.commit()
    session.refresh(ubicacion)
    return ubicacion


def update_ubicacion(
    session: Session, ubicacion: Ubicacion, data: dict[str, Any]
) -> Ubicacion:
    for key, value in data.items():
        setattr(ubicacion, key, value)
    session.add(ubicacion)
    session.commit()
    session.refresh(ubicacion)
    return ubicacion


def delete_ubicacion(session: Session, ubicacion: Ubicacion) -> None:
    session.delete(ubicacion)
    session.commit()
