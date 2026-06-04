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


class RolNoEncontrado(VoluntarioError):  # noqa: N818 — castellano
    """No existe un rol con el identificador pedido."""


class RolYaAsignado(VoluntarioError):  # noqa: N818 — castellano
    """El voluntario ya tiene una asignación activa de este rol."""


class RolNoAsignado(VoluntarioError):  # noqa: N818 — castellano
    """El voluntario no tiene una asignación activa de este rol."""


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
    actor_keycloak_id: str | None = None,
) -> Voluntario:
    """Crea un voluntario nuevo (CU-10).

    `fecha_alta` y `keycloak_id` se inyectan desde fuera para que el
    Router pueda elegir si los recibe del body, los autocompleta a
    `date.today()` o los pide al servicio de sincronización con Keycloak
    (EN-02-03).

    Si se proporciona ``actor_keycloak_id``, se registra un evento ALTA
    en el audit log (EN-02-04). El registro se hace después del INSERT
    para que el evento referencie un voluntario ya persistido.
    """

    if data.dni and repo.exists_with_dni(session, data.dni):
        raise DniDuplicado(data.dni)
    if data.email and repo.exists_with_email(session, data.email):
        raise EmailDuplicado(data.email)

    payload = data.model_dump(exclude_unset=False)
    payload["fecha_alta"] = fecha_alta or date.today()
    payload["keycloak_id"] = keycloak_id
    payload["estado"] = EstadoVoluntario.ACTIVO

    voluntario = repo.create(session, payload)
    _registrar_evento(
        session,
        voluntario_id=voluntario.id,
        tipo_str="alta",
        payload={
            "nombre": voluntario.nombre,
            "keycloak_id": keycloak_id,
            "fecha_alta": voluntario.fecha_alta.isoformat(),
        },
        actor_keycloak_id=actor_keycloak_id,
    )
    return voluntario


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
    actor_keycloak_id: str | None = None,
) -> Voluntario:
    """Soft delete operativo. Conserva el histórico y permite revertir."""

    v = repo.get(session, voluntario_id)
    if v is None:
        raise VoluntarioNoEncontrado(str(voluntario_id))
    resultado = repo.soft_delete(
        session, v, fecha_baja=fecha_baja or date.today()
    )
    _registrar_evento(
        session,
        voluntario_id=resultado.id,
        tipo_str="baja",
        payload={"fecha_baja": resultado.fecha_baja.isoformat()},
        actor_keycloak_id=actor_keycloak_id,
    )
    return resultado


def anonimizar(
    session: Session,
    voluntario_id: uuid.UUID,
    *,
    actor_keycloak_id: str | None = None,
) -> Voluntario:
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
    resultado = repo.anonimizar(session, v, placeholder_nombre=placeholder)
    # El evento se registra con el voluntario_id (preservado tras la
    # anonimización). El payload NO incluye PII: solo el placeholder.
    _registrar_evento(
        session,
        voluntario_id=resultado.id,
        tipo_str="anonimizacion",
        payload={"placeholder": placeholder},
        actor_keycloak_id=actor_keycloak_id,
    )
    return resultado


# ---------------------------------------------------------------------------
# Roles (EN-02-05)
# ---------------------------------------------------------------------------


# Rol que se asigna por defecto al dar de alta un voluntario (CU-10). Le
# da los permisos operativos base; un mando lo promociona después. Sin un
# rol el voluntario quedaría "mudo" (0 permisos, 403 en todo).
ROL_INICIAL_PRACTICAS = "voluntario_practicas"


def asignar_rol_por_nombre(
    session: Session,
    *,
    voluntario_id: uuid.UUID,
    nombre_rol: str,
    actor_keycloak_id: str | None = None,
):
    """Asigna un rol del catálogo (buscado por nombre) al voluntario en BD.

    Gemelo de :func:`asignar_rol` para los flujos que conocen el nombre
    del rol pero no su id (p. ej. el rol inicial del alta). Lanza
    :class:`RolNoEncontrado` si el nombre no está en el catálogo.
    """

    rol = repo.get_rol_por_nombre(session, nombre_rol)
    if rol is None:
        raise RolNoEncontrado(nombre_rol)
    return asignar_rol(
        session,
        voluntario_id=voluntario_id,
        rol_id=rol.id,
        actor_keycloak_id=actor_keycloak_id,
    )


def asignar_rol(
    session: Session,
    *,
    voluntario_id: uuid.UUID,
    rol_id: uuid.UUID,
    fecha_desde: date | None = None,
    actor_keycloak_id: str | None = None,
):
    """Asigna un rol del catálogo al voluntario en BD (sin tocar Keycloak).

    El router orquesta la llamada a Keycloak (vía
    :class:`KeycloakAdminClient`) ANTES de invocar este service, para
    que un fallo de KC no deje filas huérfanas en BD — mismo patrón que
    ``crear_voluntario``. Devuelve también el nombre del rol porque el
    router necesita ese dato para sincronizar con Keycloak y para la
    respuesta enriquecida.
    """

    v = repo.get(session, voluntario_id)
    if v is None:
        raise VoluntarioNoEncontrado(str(voluntario_id))

    rol = repo.get_rol(session, rol_id)
    if rol is None:
        raise RolNoEncontrado(str(rol_id))

    if repo.get_asignacion_activa(
        session, voluntario_id=voluntario_id, rol_id=rol_id
    ) is not None:
        raise RolYaAsignado(
            f"voluntario {voluntario_id} ya tiene asignado el rol "
            f"{rol.nombre} ({rol_id})"
        )

    asignacion = repo.crear_asignacion_rol(
        session,
        voluntario_id=voluntario_id,
        rol_id=rol_id,
        fecha_desde=fecha_desde or date.today(),
    )
    _registrar_evento(
        session,
        voluntario_id=voluntario_id,
        tipo_str="cambio_rol_asignado",
        payload={"rol_id": str(rol_id), "rol_nombre": rol.nombre},
        actor_keycloak_id=actor_keycloak_id,
    )
    return asignacion, rol


def quitar_rol(
    session: Session,
    *,
    voluntario_id: uuid.UUID,
    rol_id: uuid.UUID,
    fecha_hasta: date | None = None,
    actor_keycloak_id: str | None = None,
):
    """Cierra la asignación activa del par (voluntario, rol) en BD.

    Es soft delete: la fila persiste con ``fecha_hasta`` poblada para
    mantener el histórico de asignaciones. Devuelve también el nombre
    del rol para que el router pueda sincronizar con Keycloak.
    """

    v = repo.get(session, voluntario_id)
    if v is None:
        raise VoluntarioNoEncontrado(str(voluntario_id))

    rol = repo.get_rol(session, rol_id)
    if rol is None:
        raise RolNoEncontrado(str(rol_id))

    asignacion = repo.get_asignacion_activa(
        session, voluntario_id=voluntario_id, rol_id=rol_id
    )
    if asignacion is None:
        raise RolNoAsignado(
            f"voluntario {voluntario_id} no tiene asignado el rol "
            f"{rol.nombre} ({rol_id})"
        )

    cerrada = repo.cerrar_asignacion_rol(
        session, asignacion, fecha_hasta=fecha_hasta or date.today()
    )
    _registrar_evento(
        session,
        voluntario_id=voluntario_id,
        tipo_str="cambio_rol_revocado",
        payload={"rol_id": str(rol_id), "rol_nombre": rol.nombre},
        actor_keycloak_id=actor_keycloak_id,
    )
    return cerrada, rol


# ---------------------------------------------------------------------------
# Helper de audit log (EN-02-04 / US-02-06)
# ---------------------------------------------------------------------------


def _registrar_evento(
    session: Session,
    *,
    voluntario_id: uuid.UUID,
    tipo_str: str,
    payload: dict | None = None,
    actor_keycloak_id: str | None = None,
) -> None:
    """Registra un evento en el audit log con import diferido.

    El import al pie de la función evita el ciclo
    ``services/voluntarios → repositories/voluntario_evento →
    models/voluntario_evento → models/voluntario → services/voluntarios``
    que aparecería si la importación se hiciera al top-level. Es el
    mismo patrón que ``servicios.cerrar`` usa para invocar fichajes e
    inventario.

    La función nunca propaga errores del audit log para que un fallo en
    el registro no rompa el flujo operativo del voluntario.
    """

    from app.models.voluntario_evento import TipoEventoVoluntario
    from app.repositories import voluntario_evento as eventos_repo

    eventos_repo.registrar(
        session,
        voluntario_id=voluntario_id,
        tipo=TipoEventoVoluntario(tipo_str),
        payload=payload,
        actor_keycloak_id=actor_keycloak_id,
    )
