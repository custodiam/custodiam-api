"""Repository del módulo servicios (EN-03-02).

Concentra todas las queries SQLModel sobre `Servicio` y
`InscripcionServicio`. El Service llama a este módulo; el Router NUNCA
lo importa directamente.

Las funciones aquí son puras desde el punto de vista de negocio: no
validan permisos, no orquestan transiciones de estado complejas y no
lanzan HTTPException. Se limitan a leer y escribir filas.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import selectinload
from sqlmodel import Session, func, or_, select

from app.models.inscripcion_servicio import InscripcionServicio, TipoInscripcion
from app.models.servicio import EstadoServicio, Servicio, TipoServicio
from app.models.voluntario import Voluntario

# ---------------------------------------------------------------------------
# Servicio
# ---------------------------------------------------------------------------


def get(session: Session, servicio_id: uuid.UUID) -> Servicio | None:
    """Devuelve el servicio por PK, sin eager-loading."""

    return session.get(Servicio, servicio_id)


def get_full(session: Session, servicio_id: uuid.UUID) -> Servicio | None:
    """Devuelve el servicio con `inscripciones` cargadas en el mismo round-trip."""

    stmt = (
        select(Servicio)
        .where(Servicio.id == servicio_id)
        .options(selectinload(Servicio.inscripciones))
    )
    return session.exec(stmt).first()


def list_paginated(
    session: Session,
    *,
    skip: int = 0,
    limit: int = 50,
    q: str | None = None,
    estado: EstadoServicio | None = None,
    tipo: TipoServicio | None = None,
) -> tuple[list[Servicio], int]:
    """Lista paginada con filtros opcionales.

    `q` busca por `titulo` o `ubicacion` con `ILIKE`. Orden por
    `fecha_inicio` descendente (próximos primero según US-03-07; los
    pasados se hunden al final por orden inverso de fecha_inicio).
    """

    base = select(Servicio)
    if estado is not None:
        base = base.where(Servicio.estado == estado)
    if tipo is not None:
        base = base.where(Servicio.tipo == tipo)
    if q:
        pattern = f"%{q}%"
        base = base.where(
            or_(Servicio.titulo.ilike(pattern), Servicio.ubicacion.ilike(pattern))
        )

    total_stmt = select(func.count()).select_from(base.subquery())
    total = session.exec(total_stmt).one()

    items_stmt = base.order_by(Servicio.fecha_inicio.desc()).offset(skip).limit(limit)
    items = list(session.exec(items_stmt).all())
    return items, int(total)


def create(session: Session, data: dict[str, Any]) -> Servicio:
    """Inserta un servicio nuevo."""

    servicio = Servicio(**data)
    session.add(servicio)
    session.commit()
    session.refresh(servicio)
    return servicio


def update(
    session: Session,
    servicio: Servicio,
    data: dict[str, Any],
) -> Servicio:
    """Aplica un parche de campos al servicio."""

    for key, value in data.items():
        setattr(servicio, key, value)
    session.add(servicio)
    session.commit()
    session.refresh(servicio)
    return servicio


def set_estado(
    session: Session,
    servicio: Servicio,
    *,
    nuevo_estado: EstadoServicio,
    fecha_cierre=None,
    observaciones_cierre: str | None = None,
) -> Servicio:
    """Cambia el estado del servicio. El Service ya valida la transición.

    Los parámetros ``fecha_cierre`` y ``observaciones_cierre`` solo se
    aplican cuando ``nuevo_estado`` es ``CERRADO`` (la cabecera del
    servicio mantiene la huella del cierre para el reporte oficial
    del CU-07).
    """

    servicio.estado = nuevo_estado
    if nuevo_estado == EstadoServicio.CERRADO:
        if fecha_cierre is not None:
            servicio.fecha_cierre = fecha_cierre
        if observaciones_cierre is not None:
            servicio.observaciones_cierre = observaciones_cierre
    session.add(servicio)
    session.commit()
    session.refresh(servicio)
    return servicio


# ---------------------------------------------------------------------------
# Inscripciones
# ---------------------------------------------------------------------------


def get_inscripcion(
    session: Session,
    *,
    servicio_id: uuid.UUID,
    voluntario_id: uuid.UUID,
) -> InscripcionServicio | None:
    """Devuelve la inscripción del par (servicio, voluntario) si existe."""

    stmt = select(InscripcionServicio).where(
        InscripcionServicio.servicio_id == servicio_id,
        InscripcionServicio.voluntario_id == voluntario_id,
    )
    return session.exec(stmt).first()


def upsert_inscripcion(
    session: Session,
    *,
    servicio_id: uuid.UUID,
    voluntario_id: uuid.UUID,
    tipo: TipoInscripcion,
    fecha,
) -> InscripcionServicio:
    """Crea o actualiza la inscripción del par (servicio, voluntario).

    Si ya existe una inscripción, conserva su ``fecha`` original y solo
    actualiza el ``tipo`` (un voluntario inscrito que después es convocado
    no "pierde" su fecha original — la convocatoria solo eleva el tipo).
    """

    existente = get_inscripcion(
        session, servicio_id=servicio_id, voluntario_id=voluntario_id
    )
    if existente is not None:
        existente.tipo = tipo
        session.add(existente)
        session.commit()
        session.refresh(existente)
        return existente

    nueva = InscripcionServicio(
        servicio_id=servicio_id,
        voluntario_id=voluntario_id,
        tipo=tipo,
        fecha=fecha,
    )
    session.add(nueva)
    session.commit()
    session.refresh(nueva)
    return nueva


def delete_inscripcion(
    session: Session, inscripcion: InscripcionServicio
) -> None:
    """Elimina la fila. El Service valida primero que se pueda eliminar."""

    session.delete(inscripcion)
    session.commit()


def list_voluntarios_por_servicio(
    session: Session, servicio_id: uuid.UUID
) -> list[tuple[Voluntario, InscripcionServicio]]:
    """Devuelve el par (Voluntario, Inscripcion) por servicio.

    La capa Service aplana este resultado al schema agregado
    ``VoluntarioInscritoResponse`` para que el router no necesite
    transformaciones adicionales.
    """

    stmt = (
        select(Voluntario, InscripcionServicio)
        .join(
            InscripcionServicio,
            InscripcionServicio.voluntario_id == Voluntario.id,
        )
        .where(InscripcionServicio.servicio_id == servicio_id)
        .order_by(Voluntario.nombre)
    )
    return [(v, i) for v, i in session.exec(stmt).all()]


def list_ids_voluntarios_activos(session: Session) -> list[uuid.UUID]:
    """Lista los ids de voluntarios en estado ACTIVO.

    Soporte para "convocar a todos los disponibles" (US-03-04). En el
    alcance de E03 no se cruza con tabla de disponibilidades — se
    asume que todo voluntario activo es candidato. El cruce con
    disponibilidad se hará cuando la US correspondiente lo materialice.
    """

    from app.models.voluntario import EstadoVoluntario

    stmt = select(Voluntario.id).where(
        Voluntario.estado == EstadoVoluntario.ACTIVO
    )
    return list(session.exec(stmt).all())
