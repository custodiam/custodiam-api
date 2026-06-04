"""Tests del cliente Admin API de Keycloak (EN-02-03).

No tocan un Keycloak real: usan `httpx.MockTransport` para simular
las respuestas de la Admin API. El objetivo es cubrir:

- caching y renovación del token de admin
- extracción del `kc_id` desde el header `Location`
- modo deshabilitado (sin password de admin configurada)
- mapeo de errores HTTP → `KeycloakAdminError`
"""

from __future__ import annotations

import httpx
import pytest

from app.services.keycloak_admin import KeycloakAdminClient, KeycloakAdminError

REALM = "custodiam"
BASE = "http://kc:8080"
ADMIN_USERS_URL = f"{BASE}/admin/realms/{REALM}/users"
TOKEN_URL = f"{BASE}/realms/master/protocol/openid-connect/token"


def _make_client(
    handler,
    *,
    admin_password: str = "admin-pass",
) -> KeycloakAdminClient:
    transport = httpx.MockTransport(handler)
    return KeycloakAdminClient(
        base_url=BASE,
        realm=REALM,
        admin_username="admin",
        admin_password=admin_password,
        admin_client_id="admin-cli",
        http_client=httpx.Client(transport=transport),
    )


class TestEnabled:
    def test_sin_password_admin_el_cliente_esta_deshabilitado(self):
        c = KeycloakAdminClient(admin_password="")
        assert c.enabled is False

    def test_con_password_admin_el_cliente_esta_habilitado(self):
        c = KeycloakAdminClient(admin_password="x")
        assert c.enabled is True


class TestCrearUsuario:
    def test_modo_deshabilitado_devuelve_none_sin_hacer_request(self):
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(500)

        client = _make_client(handler, admin_password="")
        result = client.crear_usuario(
            username="ana", email=None, given_name="Ana", family_name="G"
        )
        assert result is None
        assert calls == []

    def test_alta_exitosa_devuelve_kc_id_del_header_location(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url == httpx.URL(TOKEN_URL):
                return httpx.Response(
                    200, json={"access_token": "tok", "expires_in": 60}
                )
            if request.url == httpx.URL(ADMIN_USERS_URL):
                return httpx.Response(
                    201,
                    headers={
                        "Location": f"{ADMIN_USERS_URL}/00000000-1111-2222-3333-444444444444"
                    },
                )
            return httpx.Response(404)

        client = _make_client(handler)
        kc_id = client.crear_usuario(
            username="ana@x.com",
            email="ana@x.com",
            given_name="Ana",
            family_name="García",
        )
        assert kc_id == "00000000-1111-2222-3333-444444444444"

    def test_alta_con_conflicto_lanza_keycloak_admin_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url == httpx.URL(TOKEN_URL):
                return httpx.Response(
                    200, json={"access_token": "tok", "expires_in": 60}
                )
            return httpx.Response(409, json={"errorMessage": "Username exists"})

        client = _make_client(handler)
        with pytest.raises(KeycloakAdminError):
            client.crear_usuario(
                username="ana",
                email=None,
                given_name="Ana",
                family_name="G",
            )

    def test_alta_con_respuesta_sin_location_lanza_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url == httpx.URL(TOKEN_URL):
                return httpx.Response(
                    200, json={"access_token": "tok", "expires_in": 60}
                )
            return httpx.Response(201)  # sin Location

        client = _make_client(handler)
        with pytest.raises(KeycloakAdminError):
            client.crear_usuario(
                username="ana",
                email=None,
                given_name="Ana",
                family_name="G",
            )


class TestDesactivarUsuario:
    def test_desactivar_idempotente_con_404(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url == httpx.URL(TOKEN_URL):
                return httpx.Response(
                    200, json={"access_token": "tok", "expires_in": 60}
                )
            return httpx.Response(404)

        client = _make_client(handler)
        # No debería lanzar excepción.
        assert client.desactivar_usuario("kc-id-inexistente") is None

    def test_desactivar_ok_con_204(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url == httpx.URL(TOKEN_URL):
                return httpx.Response(
                    200, json={"access_token": "tok", "expires_in": 60}
                )
            return httpx.Response(204)

        client = _make_client(handler)
        assert client.desactivar_usuario("kc-existente") is None

    def test_desactivar_con_500_lanza_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url == httpx.URL(TOKEN_URL):
                return httpx.Response(
                    200, json={"access_token": "tok", "expires_in": 60}
                )
            return httpx.Response(500, text="boom")

        client = _make_client(handler)
        with pytest.raises(KeycloakAdminError):
            client.desactivar_usuario("kc-x")


class TestTokenCaching:
    def test_segundo_request_no_renueva_token_dentro_del_margen(self):
        token_calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal token_calls
            if request.url == httpx.URL(TOKEN_URL):
                token_calls += 1
                return httpx.Response(
                    200, json={"access_token": "tok", "expires_in": 300}
                )
            return httpx.Response(204)

        client = _make_client(handler)
        client.desactivar_usuario("kc-1")
        client.desactivar_usuario("kc-2")
        assert token_calls == 1


class TestAsignarRolRealm:
    def test_asignar_rol_dos_calls_get_y_post(self):
        recorded: list[tuple[str, httpx.URL]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            recorded.append((request.method, request.url))
            if request.url == httpx.URL(TOKEN_URL):
                return httpx.Response(
                    200, json={"access_token": "tok", "expires_in": 60}
                )
            if request.method == "GET":
                return httpx.Response(200, json={"id": "role-uuid", "name": "voluntario"})
            return httpx.Response(204)

        client = _make_client(handler)
        client.asignar_rol_realm("kc-id", "voluntario")
        # 1 token + 1 GET rol + 1 POST mappings.
        assert len(recorded) == 3


class TestExecuteActionsEmail:
    def test_modo_deshabilitado_devuelve_none_sin_request(self):
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(500)

        client = _make_client(handler, admin_password="")
        assert client.execute_actions_email("kc-id") is None
        assert calls == []

    def test_envio_ok_usa_put_con_actions_client_id_y_lifespan(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url == httpx.URL(TOKEN_URL):
                return httpx.Response(
                    200, json={"access_token": "tok", "expires_in": 60}
                )
            captured["method"] = request.method
            captured["path"] = request.url.path
            captured["params"] = dict(request.url.params)
            captured["body"] = request.content
            return httpx.Response(204)

        client = _make_client(handler)
        client.execute_actions_email("kc-abc")

        import json

        assert captured["method"] == "PUT"
        assert captured["path"].endswith("/users/kc-abc/execute-actions-email")
        # client_id por defecto = cliente público de la app; lifespan 24 h.
        assert captured["params"]["client_id"] == "custodiam-app"
        assert captured["params"]["lifespan"] == "86400"
        assert json.loads(captured["body"]) == ["VERIFY_EMAIL", "UPDATE_PASSWORD"]

    def test_overrides_actions_client_id_y_lifespan(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url == httpx.URL(TOKEN_URL):
                return httpx.Response(
                    200, json={"access_token": "tok", "expires_in": 60}
                )
            captured["params"] = dict(request.url.params)
            captured["body"] = request.content
            return httpx.Response(204)

        client = _make_client(handler)
        client.execute_actions_email(
            "kc-abc",
            actions=["UPDATE_PASSWORD"],
            client_id="otro-cliente",
            lifespan_seconds=3600,
        )

        import json

        assert captured["params"]["client_id"] == "otro-cliente"
        assert captured["params"]["lifespan"] == "3600"
        assert json.loads(captured["body"]) == ["UPDATE_PASSWORD"]

    def test_usuario_inexistente_404_lanza_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url == httpx.URL(TOKEN_URL):
                return httpx.Response(
                    200, json={"access_token": "tok", "expires_in": 60}
                )
            return httpx.Response(404)

        client = _make_client(handler)
        with pytest.raises(KeycloakAdminError):
            client.execute_actions_email("kc-fantasma")

    def test_respuesta_inesperada_lanza_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url == httpx.URL(TOKEN_URL):
                return httpx.Response(
                    200, json={"access_token": "tok", "expires_in": 60}
                )
            return httpx.Response(500, text="boom")

        client = _make_client(handler)
        with pytest.raises(KeycloakAdminError):
            client.execute_actions_email("kc-x")
