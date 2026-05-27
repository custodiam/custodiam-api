"""Tests E2E del router de fichajes (EN-04-02 + EN-04-03 + US-04-05)."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.models.inscripcion_servicio import TipoInscripcion
from app.repositories import servicios as servicios_repo


def _inscribir(db_session, servicio_id, voluntario_id, tipo=TipoInscripcion.INSCRITO):
    return servicios_repo.upsert_inscripcion(
        db_session,
        servicio_id=servicio_id,
        voluntario_id=voluntario_id,
        tipo=tipo,
        fecha=datetime(2026, 6, 1, 8, 0),
    )


def _entrada_path(servicio_id):
    return f"/api/v1/servicios/{servicio_id}/fichaje/entrada"


def _salida_path(servicio_id):
    return f"/api/v1/servicios/{servicio_id}/fichaje/salida"


def _lista_path(servicio_id):
    return f"/api/v1/servicios/{servicio_id}/fichaje"


# ---------------------------------------------------------------------------
# Anónimo: 401 en todos los endpoints
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path_factory",
    [
        ("post", _entrada_path),
        ("post", _salida_path),
        ("get", _lista_path),
    ],
)
def test_endpoints_sin_token_devuelven_401(client, method, path_factory):
    request = getattr(client, method)
    response = request(path_factory(uuid.uuid4()))
    assert response.status_code == 401


def test_endpoints_me_sin_token_devuelven_401(client):
    assert client.get("/api/v1/fichajes/me").status_code == 401
    assert client.get("/api/v1/fichajes/me/horas").status_code == 401


# ---------------------------------------------------------------------------
# POST /servicios/{id}/fichaje/entrada
# ---------------------------------------------------------------------------


class TestEntrada:
    def test_entrada_funciona_si_inscrito_y_servicio_activo(
        self, authenticated_client, make_voluntario, servicio_activo, db_session
    ):
        v = make_voluntario(keycloak_id="test-user-id")
        _inscribir(db_session, servicio_activo.id, v.id)
        r = authenticated_client.post(_entrada_path(servicio_activo.id))
        assert r.status_code == 201
        body = r.json()
        assert body["hora_salida"] is None
        assert body["automatico"] is False

    def test_entrada_sin_voluntario_en_bd_es_404(
        self, authenticated_client, servicio_activo
    ):
        r = authenticated_client.post(_entrada_path(servicio_activo.id))
        assert r.status_code == 404

    def test_entrada_servicio_publicado_es_409(
        self,
        authenticated_client,
        make_voluntario,
        servicio_publicado,
        db_session,
    ):
        v = make_voluntario(keycloak_id="test-user-id")
        _inscribir(db_session, servicio_publicado.id, v.id)
        r = authenticated_client.post(_entrada_path(servicio_publicado.id))
        assert r.status_code == 409

    def test_entrada_sin_inscripcion_es_409(
        self, authenticated_client, make_voluntario, servicio_activo
    ):
        make_voluntario(keycloak_id="test-user-id")
        r = authenticated_client.post(_entrada_path(servicio_activo.id))
        assert r.status_code == 409

    def test_entrada_doble_es_409(
        self, authenticated_client, make_voluntario, servicio_activo, db_session
    ):
        v = make_voluntario(keycloak_id="test-user-id")
        _inscribir(db_session, servicio_activo.id, v.id)
        authenticated_client.post(_entrada_path(servicio_activo.id))
        r = authenticated_client.post(_entrada_path(servicio_activo.id))
        assert r.status_code == 409

    def test_entrada_servicio_inexistente_es_404(
        self, authenticated_client, make_voluntario
    ):
        make_voluntario(keycloak_id="test-user-id")
        r = authenticated_client.post(_entrada_path(uuid.uuid4()))
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /servicios/{id}/fichaje/salida
# ---------------------------------------------------------------------------


class TestSalida:
    def test_salida_tras_entrada(
        self, authenticated_client, make_voluntario, servicio_activo, db_session
    ):
        v = make_voluntario(keycloak_id="test-user-id")
        _inscribir(db_session, servicio_activo.id, v.id)
        authenticated_client.post(_entrada_path(servicio_activo.id))
        r = authenticated_client.post(_salida_path(servicio_activo.id))
        assert r.status_code == 200
        body = r.json()
        assert body["hora_salida"] is not None
        assert body["duracion_segundos"] is not None
        assert body["duracion_segundos"] >= 0

    def test_salida_sin_entrada_es_404(
        self, authenticated_client, make_voluntario, servicio_activo
    ):
        make_voluntario(keycloak_id="test-user-id")
        r = authenticated_client.post(_salida_path(servicio_activo.id))
        assert r.status_code == 404

    def test_salida_doble_es_404(
        self, authenticated_client, make_voluntario, servicio_activo, db_session
    ):
        v = make_voluntario(keycloak_id="test-user-id")
        _inscribir(db_session, servicio_activo.id, v.id)
        authenticated_client.post(_entrada_path(servicio_activo.id))
        authenticated_client.post(_salida_path(servicio_activo.id))
        r = authenticated_client.post(_salida_path(servicio_activo.id))
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /servicios/{id}/fichaje (lista)
# ---------------------------------------------------------------------------


class TestListadoPorServicio:
    def test_jefe_puede_listar(
        self, jefe_client, servicio_activo, make_voluntario, db_session
    ):
        ana = make_voluntario(nombre="Ana García")
        _inscribir(db_session, servicio_activo.id, ana.id)
        from app.repositories import fichajes as fichajes_repo

        fichajes_repo.create(
            db_session,
            data=dict(
                servicio_id=servicio_activo.id,
                voluntario_id=ana.id,
                hora_entrada=datetime(2026, 6, 1, 9, 0),
                hora_salida=None,
                automatico=False,
            ),
        )
        r = jefe_client.get(_lista_path(servicio_activo.id))
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1
        assert items[0]["nombre"] == "Ana García"
        assert items[0]["hora_salida"] is None

    def test_voluntario_basico_no_puede_listar(
        self, authenticated_client, servicio_activo
    ):
        r = authenticated_client.get(_lista_path(servicio_activo.id))
        assert r.status_code == 403

    def test_listado_servicio_inexistente_es_404(self, jefe_client):
        r = jefe_client.get(_lista_path(uuid.uuid4()))
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /fichajes/me y /fichajes/me/horas
# ---------------------------------------------------------------------------


class TestMisFichajes:
    def test_listar_mis_fichajes_vacio(
        self, authenticated_client, make_voluntario
    ):
        make_voluntario(keycloak_id="test-user-id")
        r = authenticated_client.get("/api/v1/fichajes/me")
        assert r.status_code == 200
        assert r.json() == []

    def test_listar_mis_fichajes_devuelve_historial(
        self, authenticated_client, make_voluntario, servicio_activo, db_session
    ):
        v = make_voluntario(keycloak_id="test-user-id")
        _inscribir(db_session, servicio_activo.id, v.id)
        from app.repositories import fichajes as fichajes_repo

        fichajes_repo.create(
            db_session,
            data=dict(
                servicio_id=servicio_activo.id,
                voluntario_id=v.id,
                hora_entrada=datetime(2026, 6, 1, 9, 0),
                hora_salida=datetime(2026, 6, 1, 10, 0),
                automatico=False,
            ),
        )
        r = authenticated_client.get("/api/v1/fichajes/me")
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1
        assert items[0]["duracion_segundos"] == 3600

    def test_horas_acumuladas_propio(
        self, authenticated_client, make_voluntario, make_servicio, db_session
    ):
        v = make_voluntario(keycloak_id="test-user-id")
        s = make_servicio()
        from app.repositories import fichajes as fichajes_repo

        fichajes_repo.create(
            db_session,
            data=dict(
                servicio_id=s.id,
                voluntario_id=v.id,
                hora_entrada=datetime(2026, 6, 1, 9, 0),
                hora_salida=datetime(2026, 6, 1, 11, 30),
                automatico=False,
            ),
        )
        r = authenticated_client.get("/api/v1/fichajes/me/horas")
        assert r.status_code == 200
        body = r.json()
        assert body["total_segundos"] == 2 * 3600 + 30 * 60
        assert body["total_horas"] == 2.5
        assert body["fichajes_cerrados"] == 1
        assert body["fichajes_abiertos"] == 0

    def test_mis_fichajes_sin_voluntario_es_404(
        self, authenticated_client
    ):
        r = authenticated_client.get("/api/v1/fichajes/me")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# US-04-05 verificación E2E: cerrar servicio cierra fichajes
# ---------------------------------------------------------------------------


class TestCierreAutomaticoE2E:
    def test_cerrar_servicio_ficha_salida_automatica(
        self, authenticated_client, make_voluntario, servicio_activo, db_session,
        client_for_role,
    ):
        v = make_voluntario(keycloak_id="test-user-id")
        _inscribir(db_session, servicio_activo.id, v.id)
        # El voluntario ficha entrada pero no salida.
        authenticated_client.post(_entrada_path(servicio_activo.id))

        # Un mando cierra el servicio (esto cambia el override de
        # `get_current_user` en la app — ver conftest).
        jefe = client_for_role(["jefe_equipo"])
        cierre = jefe.post(f"/api/v1/servicios/{servicio_activo.id}/cerrar")
        assert cierre.status_code == 200

        # Restauramos el override del voluntario original para que la
        # consulta `/me` vuelva a localizar al sub `test-user-id`.
        voluntario_cliente = client_for_role(
            ["voluntario"], sub="test-user-id"
        )
        r = voluntario_cliente.get("/api/v1/fichajes/me")
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1
        assert items[0]["hora_salida"] is not None
        assert items[0]["automatico"] is True


# ---------------------------------------------------------------------------
# Matriz RBAC condensada
# ---------------------------------------------------------------------------


class TestMatrizRbacE04:
    def test_secretario_no_puede_fichar_propio(
        self, client_for_role, servicio_activo
    ):
        # secretario NO tiene fichaje.fichar_propio.
        c = client_for_role(["secretario"])
        r = c.post(_entrada_path(servicio_activo.id))
        assert r.status_code == 403

    def test_secretario_puede_ver_voluntarios_en_servicio(
        self, client_for_role, servicio_activo
    ):
        c = client_for_role(["secretario"])
        r = c.get(_lista_path(servicio_activo.id))
        assert r.status_code == 200

    def test_tesorero_no_puede_ver_lista(
        self, client_for_role, servicio_activo
    ):
        c = client_for_role(["tesorero"])
        r = c.get(_lista_path(servicio_activo.id))
        assert r.status_code == 403
