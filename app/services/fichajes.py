"""Service del módulo fichajes (EN-04-02 + EN-04-03 + US-04-05).

Reglas de negocio del fichaje propio (CU-05 + CU-06) y del fichaje
automático al cerrar servicio (US-04-05).

Reglas para fichar entrada:

- El servicio debe estar en estado ``ACTIVO``.
- El voluntario debe estar inscrito o convocado en el servicio.
- No puede haber ya un fichaje del par (servicio, voluntario).

Reglas para fichar salida:

- Debe existir un fichaje con ``hora_entrada`` y sin ``hora_salida``.
- ``hora_salida`` se sella en la BD y la duración se deriva.

Excepciones de dominio:

- :class:`FichajeNoEncontrado` → 404
- :class:`YaFichado` → 409
- :class:`SinFichajeAbierto` → 404
- :class:`ServicioNoActivo` → 409
- :class:`VoluntarioNoInscritoNiConvocado` → 409
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlmodel import Session

from app.models.fichaje import Fichaje
from app.models.servicio import EstadoServicio
from app.repositories import fichajes as fichajes_repo
from app.repositories import servicios as servicios_repo

# ---------------------------------------------------------------------------
# Excepciones de dominio
# ---------------------------------------------------------------------------


class FichajeError(Exception):
    """Base de las excepciones de dominio del módulo fichajes."""


class FichajeNoEncontrado(FichajeError):  # noqa: N818 — castellano
    """No existe un fichaje con el identificador pedido."""


class YaFichado(FichajeError):  # noqa: N818 — castellano
    """Ya existe un fichaje del par (servicio, voluntario)."""


class SinFichajeAbierto(FichajeError):  # noqa: N818 — castellano
    """El voluntario no tiene entrada fichada pendiente de salida."""


class ServicioNoActivo(FichajeError):  # noqa: N818 — castellano
    """El servicio no está en estado ``activo`` y no admite fichajes."""


class VoluntarioNoInscritoNiConvocado(FichajeError):  # noqa: N818
    """El voluntario no figura como inscrito o convocado en el servicio."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _voluntario_puede_fichar(
    session: Session,
    *,
    servicio_id: uuid.UUID,
    voluntario_id: uuid.UUID,
) -> bool:
    """True si el voluntario está inscrito o convocado en el servicio."""

    inscripcion = servicios_repo.get_inscripcion(
        session, servicio_id=servicio_id, voluntario_id=voluntario_id
    )
    return inscripcion is not None


# ---------------------------------------------------------------------------
# Lecturas
# ---------------------------------------------------------------------------


def listar_por_servicio(
    session: Session, servicio_id: uuid.UUID
) -> list[tuple]:
    """(Voluntario, Fichaje) por servicio (US-04-04)."""

    # 404 si no existe el servicio.
    if servicios_repo.get(session, servicio_id) is None:
        from app.services.servicios import ServicioNoEncontrado

        raise ServicioNoEncontrado(str(servicio_id))
    return fichajes_repo.list_por_servicio(session, servicio_id)


def listar_por_voluntario(
    session: Session, voluntario_id: uuid.UUID
) -> list[Fichaje]:
    return fichajes_repo.list_por_voluntario(session, voluntario_id)


def horas_acumuladas(
    session: Session, voluntario_id: uuid.UUID
) -> tuple[int, int, int]:
    return fichajes_repo.horas_acumuladas(session, voluntario_id)


# ---------------------------------------------------------------------------
# Fichaje propio (CU-05 + CU-06)
# ---------------------------------------------------------------------------


def fichar_entrada(
    session: Session,
    *,
    servicio_id: uuid.UUID,
    voluntario_id: uuid.UUID,
    cuando: datetime | None = None,
) -> Fichaje:
    """CU-05. Registra la entrada del voluntario en el servicio."""

    servicio = servicios_repo.get(session, servicio_id)
    if servicio is None:
        from app.services.servicios import ServicioNoEncontrado

        raise ServicioNoEncontrado(str(servicio_id))

    if servicio.estado != EstadoServicio.ACTIVO:
        raise ServicioNoActivo(
            f"estado={servicio.estado.value}; solo se ficha en servicios activos"
        )

    if not _voluntario_puede_fichar(
        session, servicio_id=servicio_id, voluntario_id=voluntario_id
    ):
        raise VoluntarioNoInscritoNiConvocado(
            "el voluntario no está inscrito ni convocado en el servicio"
        )

    if (
        fichajes_repo.get_por_servicio_y_voluntario(
            session, servicio_id=servicio_id, voluntario_id=voluntario_id
        )
        is not None
    ):
        raise YaFichado(
            f"ya hay un fichaje del voluntario {voluntario_id} "
            f"en el servicio {servicio_id}"
        )

    return fichajes_repo.create(
        session,
        data=dict(
            servicio_id=servicio_id,
            voluntario_id=voluntario_id,
            hora_entrada=cuando or datetime.now(),
            hora_salida=None,
            automatico=False,
        ),
    )


def fichar_salida(
    session: Session,
    *,
    servicio_id: uuid.UUID,
    voluntario_id: uuid.UUID,
    cuando: datetime | None = None,
) -> Fichaje:
    """CU-06. Registra la salida del voluntario en el servicio.

    Si el fichaje ya tiene ``hora_salida``, la operación es idempotente
    a nivel HTTP pero se considera un :class:`SinFichajeAbierto` para
    que el cliente reciba 404 — no hay nada que fichar.
    """

    fichaje = fichajes_repo.get_por_servicio_y_voluntario(
        session, servicio_id=servicio_id, voluntario_id=voluntario_id
    )
    if fichaje is None or fichaje.hora_salida is not None:
        raise SinFichajeAbierto(
            f"no hay entrada fichada pendiente de salida para "
            f"voluntario {voluntario_id} en servicio {servicio_id}"
        )
    return fichajes_repo.update(
        session,
        fichaje,
        data={"hora_salida": cuando or datetime.now()},
    )


# ---------------------------------------------------------------------------
# US-04-05: fichaje automático al cerrar servicio
# ---------------------------------------------------------------------------


def cerrar_fichajes_abiertos(
    session: Session,
    *,
    servicio_id: uuid.UUID,
    cuando: datetime,
) -> list[Fichaje]:
    """Sella la ``hora_salida`` de todos los fichajes abiertos del servicio.

    Diseñado para ser invocado desde el ``cerrar()`` del servicio.
    Marca ``automatico=True`` para que se pueda distinguir esta salida
    de una explícita del voluntario. Si no hay fichajes abiertos,
    devuelve la lista vacía sin error.
    """

    abiertos = fichajes_repo.list_abiertos_por_servicio(session, servicio_id)
    actualizados = [
        fichajes_repo.update(
            session,
            fichaje,
            data={"hora_salida": cuando, "automatico": True},
        )
        for fichaje in abiertos
    ]
    return actualizados
