"""Tests del cliente Firebase Cloud Messaging (Epic E06).

No tocan un proyecto Firebase real: usan ``httpx.MockTransport`` para
simular los endpoints de Google OAuth y de FCM, más una clave RSA
generada en memoria para firmar el JWT de assertion sin necesidad de
descargar credenciales.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.models.notificacion import PrioridadNotificacion
from app.services.fcm_admin import (
    FCM_MESSAGES_ENDPOINT,
    GOOGLE_TOKEN_URL,
    FcmAdminClient,
    FcmAdminError,
)

PROJECT_ID = "custodiam-test"
FCM_URL = FCM_MESSAGES_ENDPOINT.format(project_id=PROJECT_ID)


# ---------------------------------------------------------------------------
# Fixtures de credenciales sintéticas
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _rsa_pem() -> str:
    """Clave RSA-2048 generada en memoria, válida para firmar RS256."""

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


@pytest.fixture
def service_account_json(tmp_path: Path, _rsa_pem: str) -> str:
    """Service account JSON sintético escrito en ``tmp_path``."""

    sa = {
        "type": "service_account",
        "project_id": PROJECT_ID,
        "client_email": "fcm-bot@custodiam-test.iam.gserviceaccount.com",
        "private_key": _rsa_pem,
    }
    sa_path = tmp_path / "service-account.json"
    sa_path.write_text(json.dumps(sa), encoding="utf-8")
    return str(sa_path)


def _make_client(handler, *, service_account_path: str) -> FcmAdminClient:
    transport = httpx.MockTransport(handler)
    return FcmAdminClient(
        service_account_json_path=service_account_path,
        project_id=PROJECT_ID,
        http_client=httpx.Client(transport=transport),
    )


def _make_disabled_client(handler) -> FcmAdminClient:
    transport = httpx.MockTransport(handler)
    return FcmAdminClient(
        service_account_json_path="",
        project_id="",
        http_client=httpx.Client(transport=transport),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEnabled:
    def test_sin_credenciales_el_cliente_esta_deshabilitado(self):
        c = FcmAdminClient(service_account_json_path="", project_id="")
        assert c.enabled is False

    def test_solo_project_id_no_basta_para_habilitar(self, tmp_path):
        c = FcmAdminClient(
            service_account_json_path="",
            project_id=PROJECT_ID,
        )
        assert c.enabled is False

    def test_modo_deshabilitado_no_intenta_enviar(self):
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(500)

        c = _make_disabled_client(handler)
        resultado = c.enviar(token="t", titulo="hola", cuerpo="ok")
        assert resultado is None
        assert calls == []


class TestCargaServiceAccount:
    def test_archivo_inexistente_lanza_error(self):
        with pytest.raises(FcmAdminError):
            FcmAdminClient(
                service_account_json_path="/no-existe.json",
                project_id=PROJECT_ID,
            )

    def test_json_invalido_lanza_error(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not-json", encoding="utf-8")
        with pytest.raises(FcmAdminError):
            FcmAdminClient(
                service_account_json_path=str(bad),
                project_id=PROJECT_ID,
            )

    def test_json_sin_campos_obligatorios_lanza_error(self, tmp_path):
        missing = tmp_path / "missing.json"
        missing.write_text(json.dumps({"type": "service_account"}), encoding="utf-8")
        with pytest.raises(FcmAdminError):
            FcmAdminClient(
                service_account_json_path=str(missing),
                project_id=PROJECT_ID,
            )


class TestEnviar:
    def test_envio_exitoso_devuelve_true(self, service_account_json):
        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == GOOGLE_TOKEN_URL:
                return httpx.Response(
                    200, json={"access_token": "ya29.fake", "expires_in": 3600}
                )
            if str(request.url) == FCM_URL:
                return httpx.Response(200, json={"name": "projects/x/messages/123"})
            return httpx.Response(404)

        c = _make_client(handler, service_account_path=service_account_json)
        resultado = c.enviar(token="t-abc", titulo="hola", cuerpo="ok")
        assert resultado is True

    def test_envio_con_token_invalido_devuelve_false_para_marcar_inactivo(
        self, service_account_json
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == GOOGLE_TOKEN_URL:
                return httpx.Response(
                    200, json={"access_token": "ya29.fake", "expires_in": 3600}
                )
            return httpx.Response(
                404,
                json={
                    "error": {
                        "code": 404,
                        "status": "NOT_FOUND",
                        "message": "Requested entity was not found.",
                    }
                },
            )

        c = _make_client(handler, service_account_path=service_account_json)
        assert c.enviar(token="caduco", titulo="x", cuerpo="y") is False

    def test_envio_con_5xx_lanza_fcm_admin_error(self, service_account_json):
        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == GOOGLE_TOKEN_URL:
                return httpx.Response(
                    200, json={"access_token": "ya29.fake", "expires_in": 3600}
                )
            return httpx.Response(503, text="upstream broken")

        c = _make_client(handler, service_account_path=service_account_json)
        with pytest.raises(FcmAdminError):
            c.enviar(token="t", titulo="x", cuerpo="y")

    def test_segundo_envio_no_renueva_token_dentro_del_margen(
        self, service_account_json
    ):
        token_calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal token_calls
            if str(request.url) == GOOGLE_TOKEN_URL:
                token_calls += 1
                return httpx.Response(
                    200, json={"access_token": "ya29.fake", "expires_in": 3600}
                )
            return httpx.Response(200, json={"name": "ok"})

        c = _make_client(handler, service_account_path=service_account_json)
        c.enviar(token="t1", titulo="x", cuerpo="y")
        c.enviar(token="t2", titulo="x", cuerpo="y")
        assert token_calls == 1

    def test_emergencia_marca_prioridad_alta_en_android_y_apns(
        self, service_account_json
    ):
        captured: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == GOOGLE_TOKEN_URL:
                return httpx.Response(
                    200, json={"access_token": "ya29.fake", "expires_in": 3600}
                )
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={"name": "ok"})

        c = _make_client(handler, service_account_path=service_account_json)
        c.enviar(
            token="t",
            titulo="EMERGENCIA",
            cuerpo="Activación",
            prioridad=PrioridadNotificacion.CRITICA,
            data={"servicio_id": "abc-123"},
        )

        assert len(captured) == 1
        msg = captured[0]["message"]
        assert msg["token"] == "t"
        assert msg["android"]["priority"] == "HIGH"
        assert msg["apns"]["headers"]["apns-priority"] == "10"
        assert msg["data"] == {"servicio_id": "abc-123"}

    def test_normal_marca_prioridad_normal_en_payload(self, service_account_json):
        captured: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == GOOGLE_TOKEN_URL:
                return httpx.Response(
                    200, json={"access_token": "ya29.fake", "expires_in": 3600}
                )
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={"name": "ok"})

        c = _make_client(handler, service_account_path=service_account_json)
        c.enviar(
            token="t",
            titulo="Nuevo servicio",
            cuerpo="Fecha",
            prioridad=PrioridadNotificacion.NORMAL,
        )
        msg = captured[0]["message"]
        assert msg["android"]["priority"] == "NORMAL"
        assert msg["apns"]["headers"]["apns-priority"] == "5"
        assert "data" not in msg
