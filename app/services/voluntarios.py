"""Service del módulo voluntarios (EN-02-02).

Orquesta el `Repository` y aplica las reglas de negocio del CU-10
(alta), CU-11 (modificación) y los dos flujos de DELETE diferenciados
(soft delete operativo vs. anonimización Art. 17 RGPD).

Excepciones de dominio
----------------------

Se exponen como subclases de :class:`VoluntarioError`. El Router las
captura y devuelve el código HTTP apropiado:

- :class:`VoluntarioNoEncontrado` → 404
- :class:`DniDuplicado` → 409
- :class:`EmailDuplicado` → 409
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlmodel import Session

from app.models.voluntario import EstadoVoluntario, Voluntario
from app.repositories import voluntarios as repo

if TYPE_CHECKING:
    from app.schemas.voluntario import (
        VoluntarioCreate,
        VoluntarioUpdateAdmin,
        VoluntarioUpdateSelf,
    )


class VoluntarioError(Exception):
    """Base de las excepciones de dominio del módulo voluntarios."""


class VoluntarioNoEncontrado(VoluntarioError):  # noqa: N818 — castellano
    """No existe un voluntario con el identificador pedido."""


class DniDuplicado(VoluntarioError):  # noqa: N818 — castellano
    """Ya hay otro voluntario con el mismo DNI."""


class EmailDuplicado(VoluntarioError):  # noqa: N818 — castellano
    """Ya hay otro voluntario con el mismo email."""


# ---------------------------------------------------------------------------
# Lecturas
# ---------------------------------------------------------------------------


def listar(
    session: Session,
    *,
    skip: int = 0,
    limit: int = 50,
    q: str | None = None,
    estado: EstadoVoluntario | None = None,
    rol_id: uuid.UUID | None = None,
) -> tuple[list[Voluntario], int]:
    return repo.list_paginated(
        session,
        skip=skip,
        limit=limit,
        q=q,
        estado=estado,
        rol_id=rol_id,
    )


def obtener(session: Session, voluntario_id: uuid.UUID) -> Voluntario:
    v = repo.get_full(session, voluntario_id)
    if v is None:
        raise VoluntarioNoEncontrado(str(voluntario_id))
    return v


def obtener_propio(session: Session, keycloak_id: str) -> Voluntario:
    """Devuelve la ficha completa del voluntario logueado.

    Si no existe en BD, lanza :class:`VoluntarioNoEncontrado`. Este caso
    es real durante la transición: un usuario puede tener cuenta en
    Keycloak antes de que el admin lo dé de alta en BD (la sincronización
    automática llega en EN-02-03).
    """

    v = repo.get_full_by_keycloak_id(session, keycloak_id)
    if v is None:
        raise VoluntarioNoEncontrado(f"keycloak_id={keycloak_id}")
    return v


# ---------------------------------------------------------------------------
# Escrituras
# ---------------------------------------------------------------------------


def crear(
    session: Session,
    data: VoluntarioCreate,
    *,
    fecha_alta: date | None = None,
    keycloak_id: str | None = None,
) -> Voluntario:
    """Crea un voluntario nuevo (CU-10).

    `fecha_alta` y `keycloak_id` se inyectan desde fuera para que el
    Router pueda elegir si los recibe del body, los autocompleta a
    `date.today()` o los pide al servicio de sincronización con Keycloak
    (EN-02-03).
    """

    if data.dni and repo.exists_with_dni(session, data.dni):
        raise DniDuplicado(data.dni)
    if data.email and repo.exists_with_email(session, data.email):
        raise EmailDuplicado(data.email)

    payload = data.model_dump(exclude_unset=False)
    payload["fecha_alta"] = fecha_alta or date.today()
    payload["keycloak_id"] = keycloak_id
    payload["estado"] = EstadoVoluntario.ACTIVO

    return repo.create(session, payload)


def actualizar_admin(
    session: Session,
    voluntario_id: uuid.UUID,
    data: VoluntarioUpdateAdmin,
) -> Voluntario:
    """Modificación admin (CU-11 flujo B). Permite tocar cualquier campo."""

    v = repo.get(session, voluntario_id)
    if v is None:
        raise VoluntarioNoEncontrado(str(voluntario_id))

    patch = data.model_dump(exclude_unset=True)
    if "dni" in patch and patch["dni"] and repo.exists_with_dni(
        session, patch["dni"], exclude_id=v.id
    ):
        raise DniDuplicado(patch["dni"])
    if "email" in patch and patch["email"] and repo.exists_with_email(
        session, patch["email"], exclude_id=v.id
    ):
        raise EmailDuplicado(patch["email"])

    return repo.update(session, v, patch)


def actualizar_propio(
    session: Session,
    keycloak_id: str,
    data: VoluntarioUpdateSelf,
) -> Voluntario:
    """Modificación self-service (CU-11 flujo A).

    El schema `VoluntarioUpdateSelf` ya limita los campos editables
    (datos de contacto). Aquí solo localizamos al voluntario por su
    `keycloak_id` y comprobamos colisiones de email.
    """

    v = repo.get_by_keycloak_id(session, keycloak_id)
    if v is None:
        raise VoluntarioNoEncontrado(f"keycloak_id={keycloak_id}")

    patch = data.model_dump(exclude_unset=True)
    if "email" in patch and patch["email"] and repo.exists_with_email(
        session, patch["email"], exclude_id=v.id
    ):
        raise EmailDuplicado(patch["email"])

    return repo.update(session, v, patch)


def dar_baja(
    session: Session,
    voluntario_id: uuid.UUID,
    *,
    fecha_baja: date | None = None,
) -> Voluntario:
    """Soft delete operativo. Conserva el histórico y permite revertir."""

    v = repo.get(session, voluntario_id)
    if v is None:
        raise VoluntarioNoEncontrado(str(voluntario_id))
    return repo.soft_delete(session, v, fecha_baja=fecha_baja or date.today())


def anonimizar(session: Session, voluntario_id: uuid.UUID) -> Voluntario:
    """Anonimización Art. 17 RGPD. Irreversible.

    Construye un placeholder único basado en el contador actual de
    voluntarios anonimizados. El placeholder permite que el histórico
    siga referenciando al voluntario por un nombre humano sin exponer
    PII.
    """

    v = repo.get(session, voluntario_id)
    if v is None:
        raise VoluntarioNoEncontrado(str(voluntario_id))

    siguiente = repo.count_anonimizados(session) + 1
    placeholder = f"Voluntario anonimizado #{siguiente}"
    return repo.anonimizar(session, v, placeholder_nombre=placeholder)
