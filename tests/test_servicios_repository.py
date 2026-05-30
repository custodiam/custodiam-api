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

    def test_filtro_desde_incluye_el_limite_inferior(
        self, db_session, trio_servicios
    ):
        # El trío empieza el 27-may, 1-jun y 1-jul de 2026. `desde` en el
        # arranque del 1-jun debe conservar los dos servicios de junio y
        # julio y descartar el de mayo.
        items, total = repo.list_paginated(
            db_session, desde=datetime(2026, 6, 1, 0, 0)
        )
        assert total == 2
        assert {s.titulo for s in items} == {"Romería Virgen", "Cabalgata Reyes"}

    def test_filtro_hasta_incluye_el_limite_superior(
        self, db_session, trio_servicios
    ):
        # `hasta` al final del 1-jun conserva mayo y junio, descarta julio.
        items, total = repo.list_paginated(
            db_session, hasta=datetime(2026, 6, 1, 23, 59, 59)
        )
        assert total == 2
        assert {s.titulo for s in items} == {
            "Romería Virgen",
            "Inundación río Gállego",
        }

    def test_filtro_rango_acota_por_ambos_extremos(
        self, db_session, trio_servicios
    ):
        items, total = repo.list_paginated(
            db_session,
            desde=datetime(2026, 5, 28, 0, 0),
            hasta=datetime(2026, 6, 30, 23, 59, 59),
        )
        assert total == 1
        assert items[0].titulo == "Romería Virgen"

    def test_filtro_rango_combina_con_estado(self, db_session, trio_servicios):
        items, total = repo.list_paginated(
            db_session,
            estado=EstadoServicio.PUBLICADO,
            desde=datetime(2026, 6, 15, 0, 0),
        )
        assert total == 1
        assert items[0].titulo == "Cabalgata Reyes"


class TestInscritosCount:
    """`inscritos_count` (column_property con COUNT correlacionado).

    Verifica que el conteo refleja las filas reales de
    `InscripcionServicio`, que viaja embebido en la SELECT del listado
    (sin N+1) y que `get_full` lo materializa junto a la lista de
    inscripciones cargada.
    """

    def test_servicio_sin_inscripciones_cuenta_cero(
        self, db_session, servicio_publicado
    ):
        encontrado = repo.get(db_session, servicio_publicado.id)
        assert encontrado.inscritos_count == 0

    @pytest.mark.parametrize("n", [1, 3, 5])
    def test_servicio_con_n_inscripciones(
        self, db_session, servicio_publicado, make_voluntario, make_inscripcion, n
    ):
        for i in range(n):
            vol = make_voluntario(nombre=f"Voluntario {i}")
            make_inscripcion(
                servicio_id=servicio_publicado.id, voluntario_id=vol.id
            )
        encontrado = repo.get(db_session, servicio_publicado.id)
        assert encontrado.inscritos_count == n

    def test_listado_no_tiene_n_mas_uno(
        self, db_session, make_servicio, make_voluntario, make_inscripcion
    ):
        # 5 servicios, cada uno con 2-3 inscripciones.
        for s_idx in range(5):
            servicio = make_servicio(
                titulo=f"Servicio {s_idx}",
                fecha_inicio=datetime(2026, 6, 1 + s_idx, 9, 0),
            )
            num = 2 + (s_idx % 2)  # 2 o 3 inscripciones
            for v_idx in range(num):
                vol = make_voluntario(nombre=f"Vol {s_idx}-{v_idx}")
                make_inscripcion(
                    servicio_id=servicio.id, voluntario_id=vol.id
                )

        # Contamos los SELECT que dispara `list_paginated`. Deben ser
        # exactamente 2: el total y los items (con el COUNT embebido).
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        statements: list[str] = []

        def _before_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(Engine, "before_cursor_execute", _before_cursor_execute)
        try:
            items, total = repo.list_paginated(db_session)
        finally:
            event.remove(Engine, "before_cursor_execute", _before_cursor_execute)

        assert total == 5
        assert len(items) == 5
        # Cada servicio expone su conteo embebido sin queries adicionales.
        counts = sorted(s.inscritos_count for s in items)
        assert counts == [2, 2, 2, 3, 3]
        assert len(statements) == 2, (
            f"esperaba 2 SELECT (total + items), hubo {len(statements)}: "
            + "\n---\n".join(statements)
        )

    def test_get_full_devuelve_count_y_lista_cargada(
        self, db_session, servicio_publicado, make_voluntario, make_inscripcion
    ):
        for i in range(3):
            vol = make_voluntario(nombre=f"Voluntario {i}")
            make_inscripcion(
                servicio_id=servicio_publicado.id, voluntario_id=vol.id
            )
        full = repo.get_full(db_session, servicio_publicado.id)
        assert full is not None
        assert full.inscritos_count == 3
        # La relación sigue cargada (la usan otras rutas).
        assert isinstance(full.inscripciones, list)
        assert len(full.inscripciones) == 3

    def test_inscritos_count_incluye_todos_los_tipos(
        self, db_session, servicio_publicado, make_voluntario, make_inscripcion
    ):
        # El COUNT no filtra por `tipo`: cuenta tanto a los que se apuntaron
        # (INSCRITO) como a los movilizados por un mando (CONVOCADO).
        for i in range(2):
            vol = make_voluntario(nombre=f"Inscrito {i}")
            make_inscripcion(
                servicio_id=servicio_publicado.id,
                voluntario_id=vol.id,
                tipo=TipoInscripcion.INSCRITO,
            )
        convocado = make_voluntario(nombre="Convocado 0")
        make_inscripcion(
            servicio_id=servicio_publicado.id,
            voluntario_id=convocado.id,
            tipo=TipoInscripcion.CONVOCADO,
        )

        encontrado = repo.get(db_session, servicio_publicado.id)
        assert encontrado.inscritos_count == 3


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
