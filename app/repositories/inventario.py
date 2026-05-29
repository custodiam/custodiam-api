"""Repository del módulo inventario (EN-05-02)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import selectinload
from sqlmodel import Session, func, or_, select

from app.models.asignacion_material import AsignacionMaterial, TipoAsignacion
from app.models.asignacion_vehiculo import AsignacionVehiculo
from app.models.material import EstadoInventario, Material, TipoMaterial
from app.models.vehiculo import TipoVehiculo, Vehiculo

# ---------------------------------------------------------------------------
# Material
# ---------------------------------------------------------------------------


def get_material(session: Session, material_id: uuid.UUID) -> Material | None:
    return session.get(Material, material_id)


def get_material_por_codigo(session: Session, codigo: str) -> Material | None:
    stmt = select(Material).where(Material.codigo == codigo)
    return session.exec(stmt).first()


def list_materiales(
    session: Session,
    *,
    skip: int = 0,
    limit: int = 50,
    q: str | None = None,
    estado: EstadoInventario | None = None,
    tipo: TipoMaterial | None = None,
    categoria: str | None = None,
) -> tuple[list[Material], int]:
    """Lista paginada con filtros (US-05-10)."""

    base = select(Material)
    if estado is not None:
        base = base.where(Material.estado == estado)
    if tipo is not None:
        base = base.where(Material.tipo == tipo)
    if categoria is not None:
        base = base.where(Material.categoria == categoria)
    if q:
        pattern = f"%{q}%"
        base = base.where(
            or_(Material.nombre.ilike(pattern), Material.codigo.ilike(pattern))
        )

    total_stmt = select(func.count()).select_from(base.subquery())
    total = int(session.exec(total_stmt).one())

    items_stmt = base.order_by(Material.nombre).offset(skip).limit(limit)
    items = list(session.exec(items_stmt).all())
    return items, total


def create_material(session: Session, data: dict[str, Any]) -> Material:
    material = Material(**data)
    session.add(material)
    session.commit()
    session.refresh(material)
    return material


def update_material(
    session: Session, material: Material, data: dict[str, Any]
) -> Material:
    for key, value in data.items():
        setattr(material, key, value)
    session.add(material)
    session.commit()
    session.refresh(material)
    return material


def set_estado_material(
    session: Session,
    material: Material,
    *,
    nuevo_estado: EstadoInventario,
    observaciones_incidencia: str | None = None,
) -> Material:
    material.estado = nuevo_estado
    if observaciones_incidencia is not None:
        material.observaciones_incidencia = observaciones_incidencia
    session.add(material)
    session.commit()
    session.refresh(material)
    return material


# ---------------------------------------------------------------------------
# Vehiculo
# ---------------------------------------------------------------------------


def get_vehiculo(session: Session, vehiculo_id: uuid.UUID) -> Vehiculo | None:
    return session.get(Vehiculo, vehiculo_id)


def get_vehiculo_por_codigo(
    session: Session, codigo_interno: str
) -> Vehiculo | None:
    stmt = select(Vehiculo).where(Vehiculo.codigo_interno == codigo_interno)
    return session.exec(stmt).first()


def list_vehiculos(
    session: Session,
    *,
    skip: int = 0,
    limit: int = 50,
    q: str | None = None,
    estado: EstadoInventario | None = None,
    tipo: TipoVehiculo | None = None,
) -> tuple[list[Vehiculo], int]:
    base = select(Vehiculo)
    if estado is not None:
        base = base.where(Vehiculo.estado == estado)
    if tipo is not None:
        base = base.where(Vehiculo.tipo == tipo)
    if q:
        pattern = f"%{q}%"
        base = base.where(
            or_(
                Vehiculo.codigo_interno.ilike(pattern),
                Vehiculo.matricula.ilike(pattern),
            )
        )

    total_stmt = select(func.count()).select_from(base.subquery())
    total = int(session.exec(total_stmt).one())

    items_stmt = (
        base.order_by(Vehiculo.codigo_interno).offset(skip).limit(limit)
    )
    items = list(session.exec(items_stmt).all())
    return items, total


def create_vehiculo(session: Session, data: dict[str, Any]) -> Vehiculo:
    vehiculo = Vehiculo(**data)
    session.add(vehiculo)
    session.commit()
    session.refresh(vehiculo)
    return vehiculo


def update_vehiculo(
    session: Session, vehiculo: Vehiculo, data: dict[str, Any]
) -> Vehiculo:
    for key, value in data.items():
        setattr(vehiculo, key, value)
    session.add(vehiculo)
    session.commit()
    session.refresh(vehiculo)
    return vehiculo


def set_estado_vehiculo(
    session: Session,
    vehiculo: Vehiculo,
    *,
    nuevo_estado: EstadoInventario,
    observaciones_incidencia: str | None = None,
) -> Vehiculo:
    vehiculo.estado = nuevo_estado
    if observaciones_incidencia is not None:
        vehiculo.observaciones_incidencia = observaciones_incidencia
    session.add(vehiculo)
    session.commit()
    session.refresh(vehiculo)
    return vehiculo


# ---------------------------------------------------------------------------
# AsignacionMaterial
# ---------------------------------------------------------------------------


def get_asignacion_material(
    session: Session, asignacion_id: uuid.UUID
) -> AsignacionMaterial | None:
    return session.get(AsignacionMaterial, asignacion_id)


def get_asignacion_activa_material_voluntario(
    session: Session,
    *,
    material_id: uuid.UUID,
    voluntario_id: uuid.UUID,
) -> AsignacionMaterial | None:
    """Asignación activa del par (material, voluntario) si existe."""

    stmt = select(AsignacionMaterial).where(
        AsignacionMaterial.material_id == material_id,
        AsignacionMaterial.voluntario_id == voluntario_id,
        AsignacionMaterial.fecha_devolucion.is_(None),
    )
    return session.exec(stmt).first()


def list_asignaciones_activas_material(
    session: Session, material_id: uuid.UUID
) -> list[AsignacionMaterial]:
    stmt = select(AsignacionMaterial).where(
        AsignacionMaterial.material_id == material_id,
        AsignacionMaterial.fecha_devolucion.is_(None),
    )
    return list(session.exec(stmt).all())


def list_asignaciones_activas_servicio_material(
    session: Session, servicio_id: uuid.UUID
) -> list[AsignacionMaterial]:
    """Material asignado a un servicio sin devolver (para US-05-06 + cierre)."""

    stmt = select(AsignacionMaterial).where(
        AsignacionMaterial.servicio_id == servicio_id,
        AsignacionMaterial.fecha_devolucion.is_(None),
    )
    return list(session.exec(stmt).all())


def create_asignacion_material(
    session: Session, data: dict[str, Any]
) -> AsignacionMaterial:
    asignacion = AsignacionMaterial(**data)
    session.add(asignacion)
    session.commit()
    session.refresh(asignacion)
    return asignacion


def cerrar_asignacion_material(
    session: Session,
    asignacion: AsignacionMaterial,
    *,
    cuando: datetime,
    observaciones_devolucion: str | None = None,
) -> AsignacionMaterial:
    asignacion.fecha_devolucion = cuando
    if observaciones_devolucion is not None:
        asignacion.observaciones_devolucion = observaciones_devolucion
    session.add(asignacion)
    session.commit()
    session.refresh(asignacion)
    return asignacion


def list_dotacion_activa_vehiculo(
    session: Session, vehiculo_id: uuid.UUID
) -> list[AsignacionMaterial]:
    """Dotación fija activa de un vehículo (PR3).

    Usa ``selectinload`` sobre ``material`` para evitar el N+1 al
    construir la respuesta con el nombre del material.
    """

    stmt = (
        select(AsignacionMaterial)
        .where(
            AsignacionMaterial.vehiculo_id == vehiculo_id,
            AsignacionMaterial.tipo == TipoAsignacion.DOTACION_VEHICULO,
            AsignacionMaterial.fecha_devolucion.is_(None),
        )
        .options(selectinload(AsignacionMaterial.material))
        .order_by(AsignacionMaterial.fecha_asignacion)
    )
    return list(session.exec(stmt).all())


def get_dotacion_activa(
    session: Session, asignacion_id: uuid.UUID
) -> AsignacionMaterial | None:
    """Recupera una dotación fija activa por id (PR3)."""

    stmt = select(AsignacionMaterial).where(
        AsignacionMaterial.id == asignacion_id,
        AsignacionMaterial.tipo == TipoAsignacion.DOTACION_VEHICULO,
        AsignacionMaterial.fecha_devolucion.is_(None),
    )
    return session.exec(stmt).first()


def count_unidades_asignadas_material(
    session: Session,
    material_id: uuid.UUID,
    *,
    excluir_tipo: TipoAsignacion | None = None,
) -> int:
    """Suma de cantidad de asignaciones activas de un material.

    Útil para validar stock antes de una nueva asignación. ``excluir_tipo``
    permite descontar un flujo concreto (típicamente SERVICIO para no
    pisar el stock de servicio cuando se asigna PERSONAL).
    """

    stmt = select(func.coalesce(func.sum(AsignacionMaterial.cantidad), 0)).where(
        AsignacionMaterial.material_id == material_id,
        AsignacionMaterial.fecha_devolucion.is_(None),
    )
    if excluir_tipo is not None:
        stmt = stmt.where(AsignacionMaterial.tipo != excluir_tipo)
    return int(session.exec(stmt).one())


# ---------------------------------------------------------------------------
# AsignacionVehiculo
# ---------------------------------------------------------------------------


def get_asignacion_vehiculo(
    session: Session, asignacion_id: uuid.UUID
) -> AsignacionVehiculo | None:
    return session.get(AsignacionVehiculo, asignacion_id)


def get_asignacion_activa_vehiculo(
    session: Session, vehiculo_id: uuid.UUID
) -> AsignacionVehiculo | None:
    """Asignación activa del vehículo (vehículos solo van a 1 servicio activo)."""

    stmt = select(AsignacionVehiculo).where(
        AsignacionVehiculo.vehiculo_id == vehiculo_id,
        AsignacionVehiculo.fecha_devolucion.is_(None),
    )
    return session.exec(stmt).first()


def list_asignaciones_activas_servicio_vehiculo(
    session: Session, servicio_id: uuid.UUID
) -> list[AsignacionVehiculo]:
    stmt = select(AsignacionVehiculo).where(
        AsignacionVehiculo.servicio_id == servicio_id,
        AsignacionVehiculo.fecha_devolucion.is_(None),
    )
    return list(session.exec(stmt).all())


def create_asignacion_vehiculo(
    session: Session, data: dict[str, Any]
) -> AsignacionVehiculo:
    asignacion = AsignacionVehiculo(**data)
    session.add(asignacion)
    session.commit()
    session.refresh(asignacion)
    return asignacion


def cerrar_asignacion_vehiculo(
    session: Session,
    asignacion: AsignacionVehiculo,
    *,
    cuando: datetime,
    observaciones: str | None = None,
) -> AsignacionVehiculo:
    asignacion.fecha_devolucion = cuando
    if observaciones is not None:
        asignacion.observaciones = observaciones
    session.add(asignacion)
    session.commit()
    session.refresh(asignacion)
    return asignacion
