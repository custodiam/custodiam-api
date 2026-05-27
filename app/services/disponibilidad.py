"""Service del módulo disponibilidad (US-02-04 / CU-12).

Orquesta el :mod:`app.repositories.disponibilidad` y aplica las reglas
de negocio del CU-12 (calendario mensual del propio voluntario).

Reglas:

- El voluntario solo puede marcar disponibilidad para el día actual o
  fechas futuras. Marcar una fecha pasada se rechaza con
  :class:`FechaPasada` → 422. Permitir marcar el pasado no aporta valor
  operativo (la convocatoria del CU-03 ya ocurrió o no) y abre puerta a
  inconsistencias con el histórico.
- La lectura del mes acepta cualquier ``(year, month)`` aunque sea
  pasado, porque el voluntario debe poder consultar su propio histórico
  de disponibilidad.

Excepciones de dominio
----------------------

- :class:`VoluntarioNoEncontrado` → 404 (heredado del módulo voluntarios).
- :class:`FechaPasada` → 422.
- :class:`MesInvalido` → 422.
"""

from __future__ import annotations

from datetime import date

from sqlmodel import Session

from app.models.disponibilidad import Disponibilidad
from app.repositories import disponibilidad as repo
from app.repositories import voluntarios as voluntarios_repo
from app.services.voluntarios import VoluntarioNoEncontrado


class DisponibilidadError(Exception):
    """Base de las excepciones de dominio del módulo disponibilidad."""


class FechaPasada(DisponibilidadError):  # noqa: N818 — castellano
    """La fecha solicitada es anterior a hoy y no admite cambios."""


class MesInvalido(DisponibilidadError):  # noqa: N818 — castellano
    """El par (year, month) no es un mes válido del calendario gregoriano."""


def _resolver_voluntario_id(session: Session, keycloak_id: str):
    """Mapea ``sub`` del JWT al ``id`` del voluntario o lanza 404."""

    voluntario = voluntarios_repo.get_by_keycloak_id(session, keycloak_id)
    if voluntario is None:
        raise VoluntarioNoEncontrado(f"keycloak_id={keycloak_id}")
    return voluntario.id


def obtener_mi_mes(
    session: Session,
    *,
    keycloak_id: str,
    year: int,
    month: int,
) -> list[Disponibilidad]:
    """Devuelve las disponibilidades del voluntario actual para el mes.

    No rellena días faltantes: la lista contiene solo los días en los
    que el voluntario se ha pronunciado explícitamente. El frontend
    asume "no disponible" cuando una fecha no aparece (criterio de
    aceptación de US-02-04: "por defecto, ningún día disponible").
    """

    if month < 1 or month > 12:
        raise MesInvalido(f"month debe estar en [1, 12]; recibido {month}")

    voluntario_id = _resolver_voluntario_id(session, keycloak_id)
    return repo.list_by_voluntario_mes(
        session, voluntario_id=voluntario_id, year=year, month=month
    )


def marcar_dia(
    session: Session,
    *,
    keycloak_id: str,
    fecha: date,
    disponible: bool,
    hoy: date | None = None,
) -> Disponibilidad:
    """Crea o actualiza la disponibilidad de ``fecha`` para el voluntario actual.

    El parámetro ``hoy`` está pensado para tests (permite congelar la
    fecha de referencia). En producción se omite y se usa ``date.today()``.
    """

    today = hoy or date.today()
    if fecha < today:
        raise FechaPasada(
            f"no se puede modificar la disponibilidad del {fecha.isoformat()}: "
            "es anterior a hoy"
        )

    voluntario_id = _resolver_voluntario_id(session, keycloak_id)
    return repo.upsert_dia(
        session,
        voluntario_id=voluntario_id,
        fecha=fecha,
        disponible=disponible,
    )
