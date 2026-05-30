"""Tests del repository del catálogo de ubicaciones (E10 / PR2)."""

from __future__ import annotations

import uuid

from app.repositories import ubicaciones as repo


class TestGet:
    def test_get_existente(self, db_session, ubicacion):
        encontrada = repo.get_ubicacion(db_session, ubicacion.id)
        assert encontrada is not None
        assert encontrada.id == ubicacion.id

    def test_get_inexistente_es_none(self, db_session):
        assert repo.get_ubicacion(db_session, uuid.uuid4()) is None

    def test_get_por_nombre(self, db_session, make_ubicacion):
        make_ubicacion(nombre="Base Zuera")
        encontrada = repo.get_ubicacion_por_nombre(db_session, "Base Zuera")
        assert encontrada is not None
        assert encontrada.nombre == "Base Zuera"

    def test_get_por_nombre_inexistente_es_none(self, db_session):
        assert repo.get_ubicacion_por_nombre(db_session, "No existe") is None


class TestList:
    def test_lista_vacia(self, db_session):
        items, total = repo.list_ubicaciones(db_session)
        assert items == []
        assert total == 0

    def test_lista_items_y_total(self, db_session, make_ubicacion):
        make_ubicacion(nombre="Almacén")
        make_ubicacion(nombre="Base")
        items, total = repo.list_ubicaciones(db_session)
        assert total == 2
        assert len(items) == 2

    def test_orden_por_nombre(self, db_session, make_ubicacion):
        make_ubicacion(nombre="Zaragoza")
        make_ubicacion(nombre="Almudévar")
        items, _ = repo.list_ubicaciones(db_session)
        assert [u.nombre for u in items] == ["Almudévar", "Zaragoza"]

    def test_filtro_q_por_nombre_case_insensitive(self, db_session, make_ubicacion):
        make_ubicacion(nombre="Base PC Bajo Gállego")
        make_ubicacion(nombre="Almacén central")
        items, total = repo.list_ubicaciones(db_session, q="bajo gállego")
        assert total == 1
        assert items[0].nombre == "Base PC Bajo Gállego"

    def test_paginacion(self, db_session, make_ubicacion):
        for i in range(5):
            make_ubicacion(nombre=f"Ubi {i}")
        items, total = repo.list_ubicaciones(db_session, skip=2, limit=2)
        assert total == 5
        assert len(items) == 2


class TestWrite:
    def test_create(self, db_session):
        creada = repo.create_ubicacion(
            db_session, {"nombre": "Nave 3", "descripcion": "Polígono"}
        )
        assert creada.id is not None
        assert creada.nombre == "Nave 3"
        assert creada.created_at is not None

    def test_create_con_coordenadas(self, db_session):
        creada = repo.create_ubicacion(
            db_session, {"nombre": "Punto A", "lat": 41.65, "lng": -0.88}
        )
        assert creada.lat == 41.65
        assert creada.lng == -0.88

    def test_update(self, db_session, ubicacion):
        actualizada = repo.update_ubicacion(
            db_session, ubicacion, {"descripcion": "Nueva descripción"}
        )
        assert actualizada.descripcion == "Nueva descripción"

    def test_delete(self, db_session, ubicacion):
        ubicacion_id = ubicacion.id
        repo.delete_ubicacion(db_session, ubicacion)
        assert repo.get_ubicacion(db_session, ubicacion_id) is None
