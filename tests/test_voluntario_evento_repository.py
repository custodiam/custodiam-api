"""Tests de `app.repositories.voluntario_evento` (EN-02-04 / US-02-06).

Cubre el registro de eventos con payload JSONB, la lista paginada con
filtros y los agregados para el resumen (servicios cerrados, último).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.models.inscripcion_servicio import InscripcionServicio, TipoInscripcion
from app.models.servicio import EstadoServicio
from app.models.voluntario_evento import TipoEventoVoluntario
from app.repositories import voluntario_evento as repo


@pytest.fixture
def otro_voluntario(make_voluntario):
    return make_voluntario(
        nombre="Beatriz Sanz", telefono="+34611111111", dni="22222222B"
    )


class TestRegistrar:
    def test_registra_evento_con_payload(self, db_session, voluntario):
        evento = repo.registrar(
            db_session,
            voluntario_id=voluntario.id,
            tipo=TipoEventoVoluntario.ALTA,
            payload={"campo": "valor", "n": 42},
            actor_keycloak_id="kc-admin",
        )

        assert evento.id is not None
        assert evento.voluntario_id == voluntario.id
        assert evento.tipo_evento == TipoEventoVoluntario.ALTA
        assert evento.payload == {"campo": "valor", "n": 42}
        assert evento.actor_keycloak_id == "kc-admin"
        assert evento.created_at is not None

    def test_registra_evento_sin_payload_ni_actor(self, db_session, voluntario):
        evento = repo.registrar(
            db_session,
            voluntario_id=voluntario.id,
            tipo=TipoEventoVoluntario.FICHAJE_SALIDA,
        )
        assert evento.payload is None
        assert evento.actor_keycloak_id is None


class TestListByVoluntario:
    def test_filtro_por_voluntario(self, db_session, voluntario, otro_voluntario):
        repo.registrar(
            db_session,
            voluntario_id=voluntario.id,
            tipo=TipoEventoVoluntario.ALTA,
        )
        repo.registrar(
            db_session,
            voluntario_id=otro_voluntario.id,
            tipo=TipoEventoVoluntario.ALTA,
        )

        items, total = repo.list_by_voluntario(
            db_session, voluntario_id=voluntario.id
        )
        assert total == 1
        assert items[0].voluntario_id == voluntario.id

    def test_orden_descendente_por_created_at(self, db_session, voluntario):
        primero = repo.registrar(
            db_session,
            voluntario_id=voluntario.id,
            tipo=TipoEventoVoluntario.ALTA,
        )
        segundo = repo.registrar(
            db_session,
            voluntario_id=voluntario.id,
            tipo=TipoEventoVoluntario.CAMBIO_ROL_ASIGNADO,
        )

        items, _ = repo.list_by_voluntario(
            db_session, voluntario_id=voluntario.id
        )
        # El más reciente primero.
        assert items[0].id == segundo.id
        assert items[1].id == primero.id

    def test_paginacion(self, db_session, voluntario):
        for _ in range(5):
            repo.registrar(
                db_session,
                voluntario_id=voluntario.id,
                tipo=TipoEventoVoluntario.FICHAJE_ENTRADA,
            )

        items, total = repo.list_by_voluntario(
            db_session, voluntario_id=voluntario.id, skip=2, limit=2
        )
        assert total == 5
        assert len(items) == 2

    def test_filtro_por_tipo(self, db_session, voluntario):
        repo.registrar(
            db_session,
            voluntario_id=voluntario.id,
            tipo=TipoEventoVoluntario.ALTA,
        )
        repo.registrar(
            db_session,
            voluntario_id=voluntario.id,
            tipo=TipoEventoVoluntario.FICHAJE_ENTRADA,
        )
        repo.registrar(
            db_session,
            voluntario_id=voluntario.id,
            tipo=TipoEventoVoluntario.FICHAJE_SALIDA,
        )

        items, total = repo.list_by_voluntario(
            db_session,
            voluntario_id=voluntario.id,
            tipos=[
                TipoEventoVoluntario.FICHAJE_ENTRADA,
                TipoEventoVoluntario.FICHAJE_SALIDA,
            ],
        )
        assert total == 2
        assert {e.tipo_evento for e in items} == {
            TipoEventoVoluntario.FICHAJE_ENTRADA,
            TipoEventoVoluntario.FICHAJE_SALIDA,
        }

    def test_filtro_por_rango_temporal(self, db_session, voluntario):
        e1 = repo.registrar(
            db_session,
            voluntario_id=voluntario.id,
            tipo=TipoEventoVoluntario.ALTA,
        )
        # Para filtros, usamos el created_at que asignó la BD a `e1`.
        # Filtro since estricto: si pasamos `since` futuro al evento, no aparece.
        futuro = (e1.created_at or datetime.now()) + timedelta(seconds=10)
        items, total = repo.list_by_voluntario(
            db_session, voluntario_id=voluntario.id, since=futuro
        )
        assert total == 0
        assert items == []


class TestAgregadosResumen:
    def test_count_servicios_cerrados_solo_los_cerrados(
        self,
        db_session,
        voluntario,
        make_servicio,
    ):
        s_activo = make_servicio(estado=EstadoServicio.ACTIVO)
        s_cerrado = make_servicio(estado=EstadoServicio.CERRADO)
        s_borrador = make_servicio(estado=EstadoServicio.BORRADOR)

        ahora = datetime.now()
        for s in (s_activo, s_cerrado, s_borrador):
            db_session.add(
                InscripcionServicio(
                    servicio_id=s.id,
                    voluntario_id=voluntario.id,
                    tipo=TipoInscripcion.INSCRITO,
                    fecha=ahora,
                )
            )
        db_session.commit()

        n = repo.count_servicios_cerrados_participados(db_session, voluntario.id)
        assert n == 1

    def test_ultimo_servicio_es_cerrado_mas_reciente(
        self, db_session, voluntario, make_servicio
    ):
        s_viejo = make_servicio(
            estado=EstadoServicio.CERRADO,
            fecha_inicio=datetime(2026, 1, 1, 10, 0),
            titulo="Servicio viejo",
        )
        s_reciente = make_servicio(
            estado=EstadoServicio.CERRADO,
            fecha_inicio=datetime(2026, 4, 1, 10, 0),
            titulo="Servicio reciente",
        )
        # Distractor: un servicio activo aún más reciente NO debe ganar.
        make_servicio(
            estado=EstadoServicio.ACTIVO,
            fecha_inicio=datetime(2026, 5, 1, 10, 0),
            titulo="Servicio activo",
        )

        ahora = datetime.now()
        for s in (s_viejo, s_reciente):
            db_session.add(
                InscripcionServicio(
                    servicio_id=s.id,
                    voluntario_id=voluntario.id,
                    tipo=TipoInscripcion.INSCRITO,
                    fecha=ahora,
                )
            )
        db_session.commit()

        ultimo = repo.ultimo_servicio_participado(db_session, voluntario.id)
        assert ultimo is not None
        assert ultimo.id == s_reciente.id

    def test_sin_inscripciones_devuelve_none(self, db_session, voluntario):
        ultimo = repo.ultimo_servicio_participado(db_session, voluntario.id)
        assert ultimo is None
