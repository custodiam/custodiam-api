"""Tests del service del catálogo de ubicaciones (E10 / PR2)."""

from __future__ import annotations

import uuid

import pytest

from app.schemas.ubicacion import UbicacionCreate, UbicacionUpdate
from app.services import ubicaciones as service


class TestCrear:
    def test_crear_ok(self, db_session):
        creada = service.crear_ubicacion(
            db_session, UbicacionCreate(nombre="Base Norte")
        )
        assert creada.id is not None
        assert creada.nombre == "Base Norte"

    def test_crear_con_coordenadas(self, db_session):
        creada = service.crear_ubicacion(
            db_session,
            UbicacionCreate(nombre="Punto rescate", lat=41.65, lng=-0.88),
        )
        assert creada.lat == 41.65
        assert creada.lng == -0.88

    def test_crear_nombre_duplicado_levanta_ya_existe(self, db_session, make_ubicacion):
        make_ubicacion(nombre="Base Sur")
        with pytest.raises(service.UbicacionYaExiste):
            service.crear_ubicacion(db_session, UbicacionCreate(nombre="Base Sur"))


class TestObtener:
    def test_obtener_ok(self, db_session, ubicacion):
        encontrada = service.obtener_ubicacion(db_session, ubicacion.id)
        assert encontrada.id == ubicacion.id

    def test_obtener_inexistente_levanta_no_encontrada(self, db_session):
        with pytest.raises(service.UbicacionNoEncontrada):
            service.obtener_ubicacion(db_session, uuid.uuid4())


class TestActualizar:
    def test_actualizar_ok(self, db_session, make_ubicacion):
        ubi = make_ubicacion(nombre="Antigua")
        actualizada = service.actualizar_ubicacion(
            db_session, ubi.id, UbicacionUpdate(nombre="Nueva")
        )
        assert actualizada.nombre == "Nueva"

    def test_actualizar_inexistente_levanta_no_encontrada(self, db_session):
        with pytest.raises(service.UbicacionNoEncontrada):
            service.actualizar_ubicacion(
                db_session, uuid.uuid4(), UbicacionUpdate(nombre="X")
            )

    def test_actualizar_a_nombre_de_otra_levanta_ya_existe(
        self, db_session, make_ubicacion
    ):
        make_ubicacion(nombre="Existente")
        otra = make_ubicacion(nombre="Otra")
        with pytest.raises(service.UbicacionYaExiste):
            service.actualizar_ubicacion(
                db_session, otra.id, UbicacionUpdate(nombre="Existente")
            )

    def test_actualizar_con_su_propio_nombre_no_colisiona(
        self, db_session, make_ubicacion
    ):
        ubi = make_ubicacion(nombre="Misma")
        actualizada = service.actualizar_ubicacion(
            db_session, ubi.id, UbicacionUpdate(nombre="Misma", descripcion="cambio")
        )
        assert actualizada.descripcion == "cambio"

    def test_patch_parcial_no_machaca_coordenadas(self, db_session, make_ubicacion):
        ubi = make_ubicacion(nombre="Con coords", lat=41.0, lng=-1.0)
        # PATCH que solo toca el nombre: lat/lng no se envían y deben sobrevivir.
        actualizada = service.actualizar_ubicacion(
            db_session, ubi.id, UbicacionUpdate(nombre="Renombrada")
        )
        assert actualizada.nombre == "Renombrada"
        assert actualizada.lat == 41.0
        assert actualizada.lng == -1.0


class TestEliminar:
    def test_eliminar_ok(self, db_session, ubicacion):
        ubicacion_id = ubicacion.id
        service.eliminar_ubicacion(db_session, ubicacion_id)
        with pytest.raises(service.UbicacionNoEncontrada):
            service.obtener_ubicacion(db_session, ubicacion_id)

    def test_eliminar_inexistente_levanta_no_encontrada(self, db_session):
        with pytest.raises(service.UbicacionNoEncontrada):
            service.eliminar_ubicacion(db_session, uuid.uuid4())


class TestListar:
    def test_listar_con_q(self, db_session, make_ubicacion):
        make_ubicacion(nombre="Base Centro")
        make_ubicacion(nombre="Almacén")
        items, total = service.listar_ubicaciones(db_session, q="base")
        assert total == 1
        assert items[0].nombre == "Base Centro"
