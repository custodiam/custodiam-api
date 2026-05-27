"""Tests del Repository de servicios (EN-03-02)."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.models.inscripcion_servicio import InscripcionServicio, TipoInscripcion
from app.models.servicio import EstadoServicio, TipoServicio
from app.models.voluntario import EstadoVoluntario
from app.repositories import servicios as repo


class TestGet:
    def test_get_devuelve_none_si_no_existe(self, db_session):
        assert repo.get(db_session, uuid.uuid4()) is None

    def test_get_devuelve_el_servicio_si_existe(self, db_session, servicio_borrador):
        encontrado = repo.get(db_session, servicio_borrador.id)
        assert encontrado is not None
        assert encontrado.id == servicio_borrador.id

    def test_get_full_devuelve_inscripciones_iterables(
        self, db_session, servicio_borrador
    ):
        full = repo.get_full(db_session, servicio_borrador.id)
        assert full is not None
        assert isinstance(full.inscripciones, list)


class TestListPaginated:
    @pytest.fixture
    def trio_servicios(self, make_servicio):
        return [
            make_servicio(
                titulo="Romería Virgen",
                tipo=TipoServicio.PREVENTIVO,
                fecha_inicio=datetime(2026, 6, 1, 9, 0),
            ),
            make_servicio(
                titulo="Cabalgata Reyes",
                tipo=TipoServicio.PREVENTIVO,
                estado=EstadoServicio.PUBLICADO,
                fecha_inicio=datetime(2026, 7, 1, 18, 0),
            ),
            make_servicio(
                titulo="Inundación río Gállego",
                tipo=TipoServicio.EMERGENCIA,
                estado=EstadoServicio.ACTIVO,
                fecha_inicio=datetime(2026, 5, 27, 8, 0),
                ubicacion="Zuera",
            ),
        ]

    def test_lista_vacia(self, db_session):
        items, total = repo.list_paginated(db_session)
        assert items == []
        assert total == 0

    def test_lista_devuelve_total_y_items(self, db_session, trio_servicios):
        items, total = repo.list_paginated(db_session)
        assert total == 3
        assert len(items) == 3

    def test_orden_por_fecha_inicio_descendente(self, db_session, trio_servicios):
        items, _ = repo.list_paginated(db_session)
        fechas = [s.fecha_inicio for s in items]
        assert fechas == sorted(fechas, reverse=True)

    def test_paginacion_skip_limit(self, db_session, trio_servicios):
        page1, total = repo.list_paginated(db_session, skip=0, limit=2)
        page2, _ = repo.list_paginated(db_session, skip=2, limit=2)
        assert total == 3
        assert len(page1) == 2
        assert len(page2) == 1

    def test_filtro_estado(self, db_session, trio_servicios):
        items, total = repo.list_paginated(
            db_session, estado=EstadoServicio.PUBLICADO
        )
        assert total == 1
        assert items[0].titulo == "Cabalgata Reyes"

    def test_filtro_tipo(self, db_session, trio_servicios):
        items, total = repo.list_paginated(
            db_session, tipo=TipoServicio.EMERGENCIA
        )
        assert total == 1
        assert items[0].titulo == "Inundación río Gállego"

    def test_filtro_q_busca_por_titulo_case_insensitive(
        self, db_session, trio_servicios
    ):
        items, total = repo.list_paginated(db_session, q="romería")
        assert total == 1
        assert items[0].titulo == "Romería Virgen"

    def test_filtro_q_busca_por_ubicacion(self, db_session, trio_servicios):
        items, total = repo.list_paginated(db_session, q="zuera")
        assert total == 1
        assert items[0].ubicacion == "Zuera"


class TestCreate:
    def test_create_persiste_servicio_borrador(self, db_session):
        s = repo.create(
            db_session,
            data=dict(
                titulo="Nuevo",
                tipo=TipoServicio.PREVENTIVO,
                estado=EstadoServicio.BORRADOR,
                fecha_inicio=datetime(2026, 8, 1, 9, 0),
                fecha_fin=datetime(2026, 8, 1, 14, 0),
                ubicacion="Zaragoza",
            ),
        )
        assert s.id is not None
        assert s.estado == EstadoServicio.BORRADOR

    def test_create_persiste_y_es_recuperable_por_get(self, db_session):
        s = repo.create(
            db_session,
            data=dict(
                titulo="Persistente",
                tipo=TipoServicio.FORMACION,
                estado=EstadoServicio.BORRADOR,
                fecha_inicio=datetime(2026, 9, 1, 9, 0),
                ubicacion="Salesianos",
            ),
        )
        recuperado = repo.get(db_session, s.id)
        assert recuperado is not None
        assert recuperado.titulo == "Persistente"
        assert recuperado.tipo == TipoServicio.FORMACION


class TestUpdate:
    def test_update_aplica_campos(self, db_session, servicio_borrador):
        actualizado = repo.update(
            db_session, servicio_borrador, data={"ubicacion": "Huesca"}
        )
        assert actualizado.ubicacion == "Huesca"

    def test_update_no_toca_campos_no_pedidos(self, db_session, servicio_borrador):
        original_titulo = servicio_borrador.titulo
        repo.update(db_session, servicio_borrador, data={"ubicacion": "Huesca"})
        recuperado = repo.get(db_session, servicio_borrador.id)
        assert recuperado.titulo == original_titulo


class TestSetEstado:
    def test_set_estado_publicado_no_toca_fecha_cierre(
        self, db_session, servicio_borrador
    ):
        actualizado = repo.set_estado(
            db_session, servicio_borrador, nuevo_estado=EstadoServicio.PUBLICADO
        )
        assert actualizado.estado == EstadoServicio.PUBLICADO
        assert actualizado.fecha_cierre is None

    def test_set_estado_cerrado_aplica_fecha_y_observaciones(
        self, db_session, servicio_activo
    ):
        cuando = datetime(2026, 6, 1, 15, 0)
        actualizado = repo.set_estado(
            db_session,
            servicio_activo,
            nuevo_estado=EstadoServicio.CERRADO,
            fecha_cierre=cuando,
            observaciones_cierre="Intervención completada sin incidencias",
        )
        assert actualizado.estado == EstadoServicio.CERRADO
        assert actualizado.fecha_cierre == cuando
        assert (
            actualizado.observaciones_cierre
            == "Intervención completada sin incidencias"
        )


class TestInscripciones:
    def test_get_inscripcion_inexistente(
        self, db_session, servicio_publicado, voluntario
    ):
        assert (
            repo.get_inscripcion(
                db_session,
                servicio_id=servicio_publicado.id,
                voluntario_id=voluntario.id,
            )
            is None
        )

    def test_upsert_inscripcion_crea_nueva(
        self, db_session, servicio_publicado, voluntario
    ):
        inscripcion = repo.upsert_inscripcion(
            db_session,
            servicio_id=servicio_publicado.id,
            voluntario_id=voluntario.id,
            tipo=TipoInscripcion.INSCRITO,
            fecha=datetime(2026, 5, 27, 10, 0),
        )
        assert inscripcion.id is not None
        assert inscripcion.tipo == TipoInscripcion.INSCRITO

    def test_upsert_inscripcion_actualiza_tipo_si_existe(
        self, db_session, servicio_publicado, voluntario
    ):
        fecha = datetime(2026, 5, 27, 10, 0)
        primera = repo.upsert_inscripcion(
            db_session,
            servicio_id=servicio_publicado.id,
            voluntario_id=voluntario.id,
            tipo=TipoInscripcion.INSCRITO,
            fecha=fecha,
        )
        segunda = repo.upsert_inscripcion(
            db_session,
            servicio_id=servicio_publicado.id,
            voluntario_id=voluntario.id,
            tipo=TipoInscripcion.CONVOCADO,
            fecha=datetime(2026, 5, 27, 11, 0),
        )
        assert segunda.id == primera.id
        assert segunda.tipo == TipoInscripcion.CONVOCADO

    def test_delete_inscripcion(
        self, db_session, servicio_publicado, voluntario
    ):
        inscripcion = repo.upsert_inscripcion(
            db_session,
            servicio_id=servicio_publicado.id,
            voluntario_id=voluntario.id,
            tipo=TipoInscripcion.INSCRITO,
            fecha=datetime(2026, 5, 27, 10, 0),
        )
        repo.delete_inscripcion(db_session, inscripcion)
        assert (
            repo.get_inscripcion(
                db_session,
                servicio_id=servicio_publicado.id,
                voluntario_id=voluntario.id,
            )
            is None
        )

    def test_list_voluntarios_por_servicio(
        self, db_session, servicio_publicado, make_voluntario
    ):
        ana = make_voluntario(nombre="Ana García")
        beatriz = make_voluntario(nombre="Beatriz López")
        repo.upsert_inscripcion(
            db_session,
            servicio_id=servicio_publicado.id,
            voluntario_id=ana.id,
            tipo=TipoInscripcion.INSCRITO,
            fecha=datetime(2026, 5, 27, 10, 0),
        )
        repo.upsert_inscripcion(
            db_session,
            servicio_id=servicio_publicado.id,
            voluntario_id=beatriz.id,
            tipo=TipoInscripcion.CONVOCADO,
            fecha=datetime(2026, 5, 27, 11, 0),
        )
        pares = repo.list_voluntarios_por_servicio(
            db_session, servicio_publicado.id
        )
        nombres = [v.nombre for v, _ in pares]
        assert nombres == ["Ana García", "Beatriz López"]
        tipos = [i.tipo for _, i in pares]
        assert TipoInscripcion.INSCRITO in tipos
        assert TipoInscripcion.CONVOCADO in tipos

    def test_list_ids_voluntarios_activos_solo_activos(
        self, db_session, make_voluntario
    ):
        activo = make_voluntario(nombre="Ana")
        baja = make_voluntario(nombre="Bea", estado=EstadoVoluntario.BAJA)
        ids = repo.list_ids_voluntarios_activos(db_session)
        assert activo.id in ids
        assert baja.id not in ids


def test_unique_constraint_servicio_voluntario(
    db_session, servicio_publicado, voluntario
):
    """No se pueden crear dos inscripciones para el mismo par."""

    db_session.add(
        InscripcionServicio(
            servicio_id=servicio_publicado.id,
            voluntario_id=voluntario.id,
            tipo=TipoInscripcion.INSCRITO,
            fecha=datetime(2026, 5, 27, 10, 0),
        )
    )
    db_session.commit()
    db_session.add(
        InscripcionServicio(
            servicio_id=servicio_publicado.id,
            voluntario_id=voluntario.id,
            tipo=TipoInscripcion.CONVOCADO,
            fecha=datetime(2026, 5, 27, 11, 0),
        )
    )
    with pytest.raises(Exception):  # IntegrityError, sqlalchemy.exc
        db_session.commit()
    db_session.rollback()
