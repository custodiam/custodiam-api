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


def esta_en_uso(session: Session, ubicacion_id: uuid.UUID) -> bool:
    """¿Algún material o vehículo referencia esta ubicación? (PR2).

    Soporta la protección del borrado: una ubicación en uso no se elimina
    (el FK es ``ON DELETE RESTRICT``; el service lo traduce a un 409 antes
    de llegar al constraint). Import local de los modelos del inventario
    para no acoplar el catálogo a su esquema en tiempo de carga.
    """

    from app.models.material import Material
    from app.models.vehiculo import Vehiculo

    en_material = session.exec(
        select(Material.id)
        .where(Material.ubicacion_base_id == ubicacion_id)
        .limit(1)
    ).first()
    if en_material is not None:
        return True
    en_vehiculo = session.exec(
        select(Vehiculo.id)
        .where(Vehiculo.ubicacion_base_id == ubicacion_id)
        .limit(1)
    ).first()
    return en_vehiculo is not None


def delete_ubicacion(session: Session, ubicacion: Ubicacion) -> None:
    session.delete(ubicacion)
    session.commit()
