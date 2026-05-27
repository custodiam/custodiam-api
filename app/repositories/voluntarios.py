"""Repository del módulo voluntarios (EN-02-02).

Concentra todas las queries SQLModel sobre `Voluntario` y sus
relaciones nested (acreditaciones, tallas, contactos de emergencia,
roles, disponibilidades). El Service llama a este módulo; el Router
NUNCA lo importa directamente.

Las funciones aquí son puras desde el punto de vista de negocio: no
validan permisos, no orquestan transacciones complejas y no lanzan
HTTPException. Se limitan a leer y escribir filas.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy.orm import selectinload
from sqlmodel import Session, func, or_, select

from app.models.rol import Rol
from app.models.voluntario import EstadoVoluntario, Voluntario
from app.models.voluntario_rol import VoluntarioRol


def get(session: Session, voluntario_id: uuid.UUID) -> Voluntario | None:
    """Devuelve el voluntario por PK, sin eager-loading de relaciones."""

    return session.get(Voluntario, voluntario_id)


def get_full(session: Session, voluntario_id: uuid.UUID) -> Voluntario | None:
    """Devuelve el voluntario con relaciones nested cargadas en un solo round-trip.

    Pensado para la ficha completa (GET /voluntarios/{id}). Usa
    `selectinload` en lugar de `joinedload` para evitar el row explosion
    cuando hay varias colecciones (acreditaciones + tallas + contactos)
    cargadas a la vez.
    """

    stmt = (
        select(Voluntario)
        .where(Voluntario.id == voluntario_id)
        .options(
            selectinload(Voluntario.acreditaciones),
            selectinload(Voluntario.tallas),
            selectinload(Voluntario.contactos_emergencia),
            selectinload(Voluntario.roles),
            selectinload(Voluntario.disponibilidades),
        )
    )
    return session.exec(stmt).first()


def get_by_keycloak_id(session: Session, keycloak_id: str) -> Voluntario | None:
    """Busca un voluntario por su `keycloak_id` (claim `sub` del JWT)."""

    stmt = select(Voluntario).where(Voluntario.keycloak_id == keycloak_id)
    return session.exec(stmt).first()


def get_full_by_keycloak_id(
    session: Session, keycloak_id: str
) -> Voluntario | None:
    """Variante de `get_full` localizada por `keycloak_id` (para GET /me)."""

    stmt = (
        select(Voluntario)
        .where(Voluntario.keycloak_id == keycloak_id)
        .options(
            selectinload(Voluntario.acreditaciones),
            selectinload(Voluntario.tallas),
            selectinload(Voluntario.contactos_emergencia),
            selectinload(Voluntario.roles),
            selectinload(Voluntario.disponibilidades),
        )
    )
    return session.exec(stmt).first()


def exists_with_dni(
    session: Session,
    dni: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    """True si ya hay otro voluntario con ese DNI.

    Permite excluir un id (útil para PATCH: validar unicidad sin
    autocolisionar consigo mismo).
    """

    stmt = select(Voluntario.id).where(Voluntario.dni == dni)
    if exclude_id is not None:
        stmt = stmt.where(Voluntario.id != exclude_id)
    return session.exec(stmt).first() is not None


def exists_with_email(
    session: Session,
    email: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    """True si ya hay otro voluntario con ese email."""

    stmt = select(Voluntario.id).where(Voluntario.email == email)
    if exclude_id is not None:
        stmt = stmt.where(Voluntario.id != exclude_id)
    return session.exec(stmt).first() is not None


def list_paginated(
    session: Session,
    *,
    skip: int = 0,
    limit: int = 50,
    q: str | None = None,
    estado: EstadoVoluntario | None = None,
    rol_id: uuid.UUID | None = None,
) -> tuple[list[Voluntario], int]:
    """Lista paginada de voluntarios con filtros opcionales.

    Devuelve la tupla `(items, total)` para que el caller pueda
    construir la respuesta con paginación. `q` busca por nombre,
    email o DNI con `ILIKE`. `estado` y `rol_id` son filtros exactos.
    """

    base = select(Voluntario)
    if estado is not None:
        base = base.where(Voluntario.estado == estado)
    if q:
        pattern = f"%{q}%"
        base = base.where(
            or_(
                Voluntario.nombre.ilike(pattern),
                Voluntario.email.ilike(pattern),
                Voluntario.dni.ilike(pattern),
            )
        )
    if rol_id is not None:
        # Voluntario tiene este rol con `fecha_hasta` NULL (asignación activa).
        base = base.join(VoluntarioRol).where(
            VoluntarioRol.rol_id == rol_id,
            VoluntarioRol.fecha_hasta.is_(None),
        )

    total_stmt = select(func.count()).select_from(base.subquery())
    total = session.exec(total_stmt).one()

    items_stmt = (
        base.order_by(Voluntario.nombre).offset(skip).limit(limit)
    )
    items = list(session.exec(items_stmt).all())
    return items, int(total)


def create(session: Session, data: dict[str, Any]) -> Voluntario:
    """Inserta un voluntario nuevo. El caller decide `fecha_alta` y `estado`."""

    vol = Voluntario(**data)
    session.add(vol)
    session.commit()
    session.refresh(vol)
    return vol


def update(
    session: Session,
    voluntario: Voluntario,
    data: dict[str, Any],
) -> Voluntario:
    """Aplica un parche de campos al voluntario.

    Espera un dict con solo los campos a tocar (los `None` declarados
    como "borrar" deben filtrarse antes en el Service).
    """

    for key, value in data.items():
        setattr(voluntario, key, value)
    session.add(voluntario)
    session.commit()
    session.refresh(voluntario)
    return voluntario


def soft_delete(
    session: Session,
    voluntario: Voluntario,
    *,
    fecha_baja: date,
) -> Voluntario:
    """Marca al voluntario como dado de baja y registra la fecha.

    Es reversible: cambiar `estado` a `ACTIVO` y poner `fecha_baja=None`
    reactiva. Mantiene `keycloak_id` y datos personales — el derecho al
    olvido del Art. 17 RGPD vive en `anonimizar`.
    """

    voluntario.estado = EstadoVoluntario.BAJA
    voluntario.fecha_baja = fecha_baja
    session.add(voluntario)
    session.commit()
    session.refresh(voluntario)
    return voluntario


def anonimizar(
    session: Session,
    voluntario: Voluntario,
    *,
    placeholder_nombre: str,
) -> Voluntario:
    """Anonimiza los datos personales del voluntario (Art. 17 RGPD).

    Sustituye `nombre` por un placeholder y borra `dni`, `email`,
    `foto_url`, `direccion`, `telefono` y `keycloak_id`. Conserva el
    `id` y los registros agregados (acreditaciones, fichaje, servicios)
    por interés legítimo y obligaciones contables.

    Cambia el estado a BAJA si no lo estaba ya — no se anonimizan
    voluntarios en activo (responsabilidad del Service garantizarlo,
    aquí solo se enforza por seguridad).
    """

    voluntario.nombre = placeholder_nombre
    voluntario.dni = None
    voluntario.email = None
    voluntario.foto_url = None
    voluntario.direccion = None
    voluntario.telefono = "ANONIMIZADO"
    voluntario.keycloak_id = None
    if voluntario.estado != EstadoVoluntario.BAJA:
        voluntario.estado = EstadoVoluntario.BAJA
        if voluntario.fecha_baja is None:
            voluntario.fecha_baja = date.today()
    session.add(voluntario)
    session.commit()
    session.refresh(voluntario)
    return voluntario


def count_anonimizados(session: Session) -> int:
    """Cuenta voluntarios anonimizados, para construir el placeholder `#N`.

    Usa el patrón "Voluntario anonimizado #<N+1>" donde N es la cuenta
    actual de anonimizados. Filtra por `nombre LIKE 'Voluntario anonimizado #%'`
    en lugar de mirar `keycloak_id IS NULL`: voluntarios pre-Keycloak
    también tienen `keycloak_id=NULL` y no son anónimos.
    """

    stmt = select(func.count()).select_from(Voluntario).where(
        Voluntario.nombre.ilike("Voluntario anonimizado #%")
    )
    return int(session.exec(stmt).one())


# ---------------------------------------------------------------------------
# Roles (EN-02-05)
# ---------------------------------------------------------------------------


def get_rol(session: Session, rol_id: uuid.UUID) -> Rol | None:
    """Devuelve un rol del catálogo por PK."""

    return session.get(Rol, rol_id)


def list_roles_catalogo(session: Session) -> list[Rol]:
    """Devuelve todos los roles del catálogo, ordenados por nivel ascendente.

    El catálogo es pequeño (~12 entradas, una por cada rol del realm de
    Keycloak), así que se devuelve sin paginar. El frontend lo usa para
    construir el selector de rol del formulario de asignación.
    """

    stmt = select(Rol).order_by(Rol.nivel, Rol.nombre)
    return list(session.exec(stmt).all())


def get_asignacion_activa(
    session: Session,
    *,
    voluntario_id: uuid.UUID,
    rol_id: uuid.UUID,
) -> VoluntarioRol | None:
    """Asignación activa (sin ``fecha_hasta``) del par voluntario+rol."""

    stmt = select(VoluntarioRol).where(
        VoluntarioRol.voluntario_id == voluntario_id,
        VoluntarioRol.rol_id == rol_id,
        VoluntarioRol.fecha_hasta.is_(None),
    )
    return session.exec(stmt).first()


def list_asignaciones_activas(
    session: Session, voluntario_id: uuid.UUID
) -> list[VoluntarioRol]:
    """Asignaciones de rol activas del voluntario."""

    stmt = select(VoluntarioRol).where(
        VoluntarioRol.voluntario_id == voluntario_id,
        VoluntarioRol.fecha_hasta.is_(None),
    )
    return list(session.exec(stmt).all())


def crear_asignacion_rol(
    session: Session,
    *,
    voluntario_id: uuid.UUID,
    rol_id: uuid.UUID,
    fecha_desde: date,
) -> VoluntarioRol:
    """Crea una asignación voluntario→rol con ``fecha_hasta=None``."""

    asignacion = VoluntarioRol(
        voluntario_id=voluntario_id,
        rol_id=rol_id,
        fecha_desde=fecha_desde,
    )
    session.add(asignacion)
    session.commit()
    session.refresh(asignacion)
    return asignacion


def cerrar_asignacion_rol(
    session: Session,
    asignacion: VoluntarioRol,
    *,
    fecha_hasta: date,
) -> VoluntarioRol:
    """Marca ``fecha_hasta`` para "cerrar" la asignación (soft delete)."""

    asignacion.fecha_hasta = fecha_hasta
    session.add(asignacion)
    session.commit()
    session.refresh(asignacion)
    return asignacion
