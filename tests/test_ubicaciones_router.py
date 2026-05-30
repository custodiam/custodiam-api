"""Tests E2E del router del catálogo de ubicaciones (E10 / PR2).

Matriz RBAC ejercida:

- ``inventario.ver`` (jefe_equipo+) → lectura (GET listar / detalle).
- ``ubicaciones.crear`` (jefe_seccion+) → escritura (POST / PATCH / DELETE).

Por tanto ``jefe_equipo`` ve pero no escribe, y el voluntario básico ni ve.
"""

from __future__ import annotations

import uuid

import pytest

BASE = "/api/v1/ubicaciones"


# ---------------------------------------------------------------------------
# Anónimo: 401
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", BASE),
        ("get", f"{BASE}/{uuid.uuid4()}"),
        ("post", BASE),
        ("patch", f"{BASE}/{uuid.uuid4()}"),
        ("delete", f"{BASE}/{uuid.uuid4()}"),
    ],
)
def test_endpoints_sin_token_devuelven_401(client, method, path):
    request = getattr(client, method)
    response = request(path) if method in ("get", "delete") else request(path, json={})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------


class TestListar:
    def test_lista_vacia(self, jefe_client):
        r = jefe_client.get(BASE)
        assert r.status_code == 200
        assert r.json() == []
        assert r.headers["X-Total-Count"] == "0"

    def test_lista_items_y_total(self, jefe_client, make_ubicacion):
        make_ubicacion(nombre="Base")
        make_ubicacion(nombre="Almacén")
        r = jefe_client.get(BASE)
        assert r.status_code == 200
        assert r.headers["X-Total-Count"] == "2"

    def test_filtro_q(self, jefe_client, make_ubicacion):
        make_ubicacion(nombre="Base PC Bajo Gállego")
        make_ubicacion(nombre="Almacén central")
        r = jefe_client.get(BASE, params={"q": "gállego"})
        assert r.status_code == 200
        assert [u["nombre"] for u in r.json()] == ["Base PC Bajo Gállego"]

    def test_voluntario_basico_no_puede_listar(self, authenticated_client):
        r = authenticated_client.get(BASE)
        assert r.status_code == 403


class TestObtener:
    def test_obtener_existente(self, jefe_client, ubicacion):
        r = jefe_client.get(f"{BASE}/{ubicacion.id}")
        assert r.status_code == 200
        assert r.json()["id"] == str(ubicacion.id)

    def test_obtener_inexistente_es_404(self, jefe_client):
        r = jefe_client.get(f"{BASE}/{uuid.uuid4()}")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Creación
# ---------------------------------------------------------------------------


class TestCrear:
    def test_jefe_seccion_crea_201(self, client_for_role):
        cliente = client_for_role(["jefe_seccion"])
        r = cliente.post(BASE, json={"nombre": "Nave nueva", "descripcion": "Pol."})
        assert r.status_code == 201
        body = r.json()
        assert body["nombre"] == "Nave nueva"
        assert body["id"]

    def test_crea_con_coordenadas(self, client_for_role):
        cliente = client_for_role(["jefe_seccion"])
        r = cliente.post(BASE, json={"nombre": "Punto A", "lat": 41.65, "lng": -0.88})
        assert r.status_code == 201
        assert r.json()["lat"] == 41.65

    def test_jefe_equipo_no_puede_crear_403(self, jefe_client):
        r = jefe_client.post(BASE, json={"nombre": "X"})
        assert r.status_code == 403

    def test_voluntario_no_puede_crear_403(self, authenticated_client):
        r = authenticated_client.post(BASE, json={"nombre": "X"})
        assert r.status_code == 403

    def test_nombre_duplicado_es_409(self, client_for_role, make_ubicacion):
        make_ubicacion(nombre="Repetida")
        cliente = client_for_role(["jefe_seccion"])
        r = cliente.post(BASE, json={"nombre": "Repetida"})
        assert r.status_code == 409

    def test_solo_lat_sin_lng_es_422(self, client_for_role):
        cliente = client_for_role(["jefe_seccion"])
        r = cliente.post(BASE, json={"nombre": "Coord parcial", "lat": 41.0})
        assert r.status_code == 422

    def test_lat_fuera_de_rango_es_422(self, client_for_role):
        cliente = client_for_role(["jefe_seccion"])
        r = cliente.post(BASE, json={"nombre": "Fuera", "lat": 200.0, "lng": 0.0})
        assert r.status_code == 422

    def test_nombre_vacio_es_422(self, client_for_role):
        cliente = client_for_role(["jefe_seccion"])
        r = cliente.post(BASE, json={"nombre": ""})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Edición
# ---------------------------------------------------------------------------


class TestActualizar:
    def test_actualizar_ok(self, client_for_role, make_ubicacion):
        ubi = make_ubicacion(nombre="Antes")
        cliente = client_for_role(["jefe_seccion"])
        r = cliente.patch(f"{BASE}/{ubi.id}", json={"nombre": "Después"})
        assert r.status_code == 200
        assert r.json()["nombre"] == "Después"

    def test_actualizar_inexistente_es_404(self, client_for_role):
        cliente = client_for_role(["jefe_seccion"])
        r = cliente.patch(f"{BASE}/{uuid.uuid4()}", json={"nombre": "X"})
        assert r.status_code == 404

    def test_actualizar_a_nombre_existente_es_409(self, client_for_role, make_ubicacion):
        make_ubicacion(nombre="Ocupado")
        otra = make_ubicacion(nombre="Libre")
        cliente = client_for_role(["jefe_seccion"])
        r = cliente.patch(f"{BASE}/{otra.id}", json={"nombre": "Ocupado"})
        assert r.status_code == 409

    def test_jefe_equipo_no_puede_actualizar_403(self, jefe_client, make_ubicacion):
        ubi = make_ubicacion(nombre="Intocable")
        r = jefe_client.patch(f"{BASE}/{ubi.id}", json={"nombre": "X"})
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Borrado
# ---------------------------------------------------------------------------


class TestEliminar:
    def test_eliminar_ok_204(self, client_for_role, make_ubicacion):
        ubi = make_ubicacion(nombre="Borrable")
        cliente = client_for_role(["jefe_seccion"])
        r = cliente.delete(f"{BASE}/{ubi.id}")
        assert r.status_code == 204

    def test_eliminar_inexistente_es_404(self, client_for_role):
        cliente = client_for_role(["jefe_seccion"])
        r = cliente.delete(f"{BASE}/{uuid.uuid4()}")
        assert r.status_code == 404

    def test_jefe_equipo_no_puede_eliminar_403(self, jefe_client, make_ubicacion):
        ubi = make_ubicacion(nombre="Persistente")
        r = jefe_client.delete(f"{BASE}/{ubi.id}")
        assert r.status_code == 403
