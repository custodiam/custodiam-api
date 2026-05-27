"""Tests del router `/api/v1/dispositivos` (Epic E06).

Cubre los tres endpoints (POST registrar, GET /me, DELETE), el RBAC y
las reglas de propiedad (no operar dispositivos de otros voluntarios).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.security import get_current_user
from app.main import app
from app.models.dispositivo import PlataformaDispositivo
from app.repositories import dispositivos as repo

API = "/api/v1/dispositivos"


@pytest.fixture
def yo(make_voluntario):
    """Voluntario vinculado al ``sub`` del cliente autenticado por defecto."""

    return make_voluntario(keycloak_id="test-user-id")


@pytest.fixture
def otro_voluntario(make_voluntario):
    return make_voluntario(
        keycloak_id="kc-otro-user",
        nombre="Beatriz Sanz",
        telefono="+34611111111",
        dni="22222222B",
    )


class TestRegistrar:
    def test_201_crea_nuevo_dispositivo(
        self, authenticated_client: TestClient, db_session, yo
    ):
        response = authenticated_client.post(
            API,
            json={
                "fcm_token": "token-android-1",
                "plataforma": "android",
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["fcm_token"] == "token-android-1"
        assert body["plataforma"] == "android"
        assert body["activo"] is True
        assert body["voluntario_id"] == str(yo.id)

    def test_post_dos_veces_con_mismo_token_es_idempotente(
        self, authenticated_client: TestClient, db_session, yo
    ):
        primero = authenticated_client.post(
            API,
            json={"fcm_token": "token-x", "plataforma": "ios"},
        )
        segundo = authenticated_client.post(
            API,
            json={"fcm_token": "token-x", "plataforma": "ios"},
        )

        assert primero.status_code == 201
        assert segundo.status_code == 201
        assert primero.json()["id"] == segundo.json()["id"]

    def test_sin_voluntario_en_bd_devuelve_404_amigable(
        self, authenticated_client: TestClient, db_session
    ):
        # Sin fixture `yo` no hay voluntario en BD.
        response = authenticated_client.post(
            API,
            json={"fcm_token": "token-cualquiera", "plataforma": "web"},
        )
        assert response.status_code == 404
        assert "Keycloak" in response.json()["detail"]

    def test_admin_puede_registrar_token(
        self, admin_client: TestClient, db_session, make_voluntario
    ):
        make_voluntario(keycloak_id="admin-user-id")
        response = admin_client.post(
            API,
            json={"fcm_token": "token-admin", "plataforma": "web"},
        )
        assert response.status_code == 201

    def test_sin_autenticacion_devuelve_401(self, client: TestClient):
        response = client.post(
            API,
            json={"fcm_token": "x", "plataforma": "android"},
        )
        assert response.status_code == 401


class TestListarMios:
    def test_devuelve_solo_los_propios_y_activos(
        self, authenticated_client: TestClient, db_session, yo, otro_voluntario
    ):
        repo.upsert(
            db_session,
            voluntario_id=yo.id,
            fcm_token="t-mio-1",
            plataforma=PlataformaDispositivo.ANDROID,
        )
        baja = repo.upsert(
            db_session,
            voluntario_id=yo.id,
            fcm_token="t-mio-baja",
            plataforma=PlataformaDispositivo.IOS,
        )
        repo.desactivar(db_session, baja)
        repo.upsert(
            db_session,
            voluntario_id=otro_voluntario.id,
            fcm_token="t-otro",
            plataforma=PlataformaDispositivo.WEB,
        )

        response = authenticated_client.get(f"{API}/me")
        assert response.status_code == 200
        tokens = [d["fcm_token"] for d in response.json()]
        assert tokens == ["t-mio-1"]


class TestDarBaja:
    def test_baja_propia_devuelve_204_y_desactiva(
        self, authenticated_client: TestClient, db_session, yo
    ):
        d = repo.upsert(
            db_session,
            voluntario_id=yo.id,
            fcm_token="t",
            plataforma=PlataformaDispositivo.ANDROID,
        )

        response = authenticated_client.delete(f"{API}/{d.id}")
        assert response.status_code == 204

        recargado = repo.get(db_session, d.id)
        assert recargado is not None
        assert recargado.activo is False

    def test_baja_de_otro_voluntario_devuelve_403(
        self,
        authenticated_client: TestClient,
        db_session,
        yo,
        otro_voluntario,
    ):
        ajeno = repo.upsert(
            db_session,
            voluntario_id=otro_voluntario.id,
            fcm_token="t-ajeno",
            plataforma=PlataformaDispositivo.WEB,
        )

        response = authenticated_client.delete(f"{API}/{ajeno.id}")
        assert response.status_code == 403

    def test_baja_de_id_inexistente_devuelve_404(
        self, authenticated_client: TestClient, yo
    ):
        response = authenticated_client.delete(f"{API}/{uuid.uuid4()}")
        assert response.status_code == 404


class TestRbacSinPermiso:
    def test_rol_desconocido_recibe_403(
        self, client_for_role, db_session, make_voluntario
    ):
        c = client_for_role(roles=["rol_inexistente"])
        # Aseguramos voluntario en BD para que el 403 sea por permiso,
        # no por falta de fixture.
        make_voluntario(
            keycloak_id="user-rol_inexistente", dni="00000000Z"
        )

        response = c.post(
            API,
            json={"fcm_token": "t", "plataforma": "android"},
        )
        assert response.status_code == 403
        # Defensa: limpiar override para no contaminar siguientes tests.
        app.dependency_overrides.pop(get_current_user, None)
