"""Service del módulo voluntario_evento (EN-02-04 / US-02-06).

Orquesta el :mod:`app.repositories.voluntario_evento` para los endpoints
del historial del voluntario actual y compone el agregado del resumen
(horas + servicios participados + último servicio) leyendo directamente
de las tablas operativas (no del audit log) para que la cifra refleje
la verdad de los datos, no la verdad del registro.

Decisión defendible: ``horas_totales`` se calcula desde ``fichajes``,
no agregando los eventos ``FICHAJE_ENTRADA`` / ``FICHAJE_SALIDA``. El
audit log es informativo; los fichajes son la fuente canónica. Si un
evento se perdiera por error (caída, race) las horas seguirían siendo
correctas.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlmodel import Session

from app.models.voluntario_evento import TipoEventoVoluntario, VoluntarioEvento
from app.repositories import fichajes as fichajes_repo
from app.repositories import voluntario_evento as repo
from app.repositories import voluntarios as voluntarios_repo
from app.schemas.voluntario_evento import (
    ResumenVoluntarioResponse,
    UltimoServicioResumen,
)
from app.services.voluntarios import VoluntarioNoEncontrado


def _resolver_voluntario_id(session: Session, keycloak_id: str):
    voluntario = voluntarios_repo.get_by_keycloak_id(session, keycloak_id)
    if voluntario is None:
        raise VoluntarioNoEncontrado(f"keycloak_id={keycloak_id}")
    return voluntario.id


def obtener_historial_propio(
    session: Session,
    *,
    keycloak_id: str,
    skip: int = 0,
    limit: int = 50,
    tipos: Sequence[TipoEventoVoluntario] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> tuple[list[VoluntarioEvento], int]:
    """Lista paginada del histórico del voluntario actual."""

    voluntario_id = _resolver_voluntario_id(session, keycloak_id)
    return repo.list_by_voluntario(
        session,
        voluntario_id=voluntario_id,
        skip=skip,
        limit=limit,
        tipos=tipos,
        since=since,
        until=until,
    )


def obtener_resumen_propio(
    session: Session, *, keycloak_id: str
) -> ResumenVoluntarioResponse:
    """Resumen agregado del voluntario actual (US-02-06)."""

    voluntario_id = _resolver_voluntario_id(session, keycloak_id)

    seg_totales, _n_cerrados, _n_abiertos = fichajes_repo.horas_acumuladas(
        session, voluntario_id
    )
    servicios_realizados = repo.count_servicios_cerrados_participados(
        session, voluntario_id
    )
    ultimo = repo.ultimo_servicio_participado(session, voluntario_id)
    ultimo_resumen: UltimoServicioResumen | None = None
    if ultimo is not None:
        ultimo_resumen = UltimoServicioResumen(
            servicio_id=ultimo.id,
            titulo=ultimo.titulo,
            fecha_inicio=ultimo.fecha_inicio,
        )

    return ResumenVoluntarioResponse(
        segundos_totales=seg_totales,
        horas_totales=seg_totales // 3600,
        servicios_realizados=servicios_realizados,
        ultimo_servicio=ultimo_resumen,
    )
