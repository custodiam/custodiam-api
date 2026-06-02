"""Tests de las coordenadas geográficas opcionales del Servicio (PR2-geo, SP-09).

El cliente puede aportar ``ubicacion_lat`` / ``ubicacion_lng`` al crear o
actualizar un servicio. El backend solo persiste (sin geocoding server-side).
Reglas de validación, fijadas en Pydantic (no como CHECK en BD):

- Rango: ``lat`` ∈ [-90, 90], ``lng`` ∈ [-180, 180].
- "Ambos o ninguno": no se admite enviar solo ``lat`` o solo ``lng``.

Los servicios históricos (sin coordenadas) quedan a ``NULL``, nunca ``0.0``.
"""

from __future__ import annotations

BASE = "/api/v1/servicios"


def _payload(**overrides) -> dict:
    base = dict(
        titulo="Servicio con coordenadas",
        tipo="preventivo",
        fecha_inicio="2026-08-01T09:00:00",
        fecha_fin="2026-08-01T14:00:00",
        ubicacion="Zaragoza, Plaza del Pilar",
    )
    base.update(overrides)
    return base


class TestPersistenciaCoordenadas:
    def test_crear_con_lat_lng_validos_persiste_y_expone_en_detalle(
        self, client_for_role
    ):
        c = client_for_role(["jefe_equipo"])
        r = c.post(
            BASE,
            json=_payload(ubicacion_lat=41.6561, ubicacion_lng=-0.8773),
        )
        assert r.status_code == 201
        body = r.json()
        assert body["ubicacion_lat"] == 41.6561
        assert body["ubicacion_lng"] == -0.8773

        # Se exponen también al volver a leer el detalle.
        detalle = c.get(f"{BASE}/{body['id']}")
        assert detalle.status_code == 200
        assert detalle.json()["ubicacion_lat"] == 41.6561
        assert detalle.json()["ubicacion_lng"] == -0.8773

    def test_coordenadas_se_exponen_en_listado_summary(self, client_for_role):
        c = client_for_role(["jefe_equipo"])
        creado = c.post(
            BASE,
            json=_payload(ubicacion_lat=42.1192, ubicacion_lng=-0.4080),
        )
        assert creado.status_code == 201

        r = c.get(BASE)
        assert r.status_code == 200
        por_id = {s["id"]: s for s in r.json()}
        item = por_id[creado.json()["id"]]
        assert item["ubicacion_lat"] == 42.1192
        assert item["ubicacion_lng"] == -0.4080

    def test_crear_sin_coordenadas_deja_ambos_null(self, client_for_role):
        c = client_for_role(["jefe_equipo"])
        r = c.post(BASE, json=_payload())
        assert r.status_code == 201
        body = r.json()
        # NULL, no 0.0 (los históricos no tienen coordenadas).
        assert body["ubicacion_lat"] is None
        assert body["ubicacion_lng"] is None

    def test_limites_de_rango_son_validos(self, client_for_role):
        c = client_for_role(["jefe_equipo"])
        r = c.post(
            BASE,
            json=_payload(ubicacion_lat=-90.0, ubicacion_lng=180.0),
        )
        assert r.status_code == 201
        assert r.json()["ubicacion_lat"] == -90.0
        assert r.json()["ubicacion_lng"] == 180.0


class TestValidacionRango:
    def test_lat_fuera_de_rango_es_422(self, client_for_role):
        c = client_for_role(["jefe_equipo"])
        r = c.post(
            BASE,
            json=_payload(ubicacion_lat=91.0, ubicacion_lng=0.0),
        )
        assert r.status_code == 422

    def test_lng_fuera_de_rango_es_422(self, client_for_role):
        c = client_for_role(["jefe_equipo"])
        r = c.post(
            BASE,
            json=_payload(ubicacion_lat=0.0, ubicacion_lng=181.0),
        )
        assert r.status_code == 422

    def test_lat_negativa_fuera_de_rango_es_422(self, client_for_role):
        c = client_for_role(["jefe_equipo"])
        r = c.post(
            BASE,
            json=_payload(ubicacion_lat=-90.1, ubicacion_lng=0.0),
        )
        assert r.status_code == 422


class TestAmbosONinguno:
    def test_solo_lat_es_422(self, client_for_role):
        c = client_for_role(["jefe_equipo"])
        r = c.post(BASE, json=_payload(ubicacion_lat=41.65))
        assert r.status_code == 422

    def test_solo_lng_es_422(self, client_for_role):
        c = client_for_role(["jefe_equipo"])
        r = c.post(BASE, json=_payload(ubicacion_lng=-0.87))
        assert r.status_code == 422


class TestActualizarCoordenadas:
    def test_patch_fija_coordenadas_en_servicio_sin_ellas(
        self, client_for_role, servicio_borrador
    ):
        c = client_for_role(["jefe_equipo"])
        r = c.patch(
            f"{BASE}/{servicio_borrador.id}",
            json={"ubicacion_lat": 41.6561, "ubicacion_lng": -0.8773},
        )
        assert r.status_code == 200
        assert r.json()["ubicacion_lat"] == 41.6561
        assert r.json()["ubicacion_lng"] == -0.8773

    def test_patch_actualiza_coordenadas_existentes(
        self, client_for_role, make_servicio
    ):
        servicio = make_servicio(ubicacion_lat=40.0, ubicacion_lng=-3.0)
        c = client_for_role(["jefe_equipo"])
        r = c.patch(
            f"{BASE}/{servicio.id}",
            json={"ubicacion_lat": 41.6561, "ubicacion_lng": -0.8773},
        )
        assert r.status_code == 200
        assert r.json()["ubicacion_lat"] == 41.6561
        assert r.json()["ubicacion_lng"] == -0.8773

    def test_patch_solo_lat_es_422(self, client_for_role, servicio_borrador):
        c = client_for_role(["jefe_equipo"])
        r = c.patch(
            f"{BASE}/{servicio_borrador.id}",
            json={"ubicacion_lat": 41.6561},
        )
        assert r.status_code == 422

    def test_patch_lat_fuera_de_rango_es_422(
        self, client_for_role, servicio_borrador
    ):
        c = client_for_role(["jefe_equipo"])
        r = c.patch(
            f"{BASE}/{servicio_borrador.id}",
            json={"ubicacion_lat": 100.0, "ubicacion_lng": 0.0},
        )
        assert r.status_code == 422
