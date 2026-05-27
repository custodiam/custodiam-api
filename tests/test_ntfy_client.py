"""Tests del cliente ntfy (Epic E06).

Usa ``httpx.MockTransport`` para simular el endpoint de publicación de
ntfy sin necesitar un servidor real corriendo.
"""

from __future__ import annotations

import httpx
import pytest

from app.models.notificacion import PrioridadNotificacion
from app.services.ntfy_client import NtfyClient, NtfyError

BASE = "http://ntfy.test"


def _make_client(handler, *, enabled: bool = True, **kwargs) -> NtfyClient:
    transport = httpx.MockTransport(handler)
    return NtfyClient(
        base_url=BASE,
        enabled=enabled,
        http_client=httpx.Client(transport=transport),
        **kwargs,
    )


class TestEnabled:
    def test_enabled_falso_aunque_haya_url(self):
        c = NtfyClient(base_url=BASE, enabled=False)
        assert c.enabled is False

    def test_enabled_true_con_url(self):
        c = NtfyClient(base_url=BASE, enabled=True)
        assert c.enabled is True


class TestEnviar:
    def test_modo_deshabilitado_no_intenta_publicar(self):
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(500)

        c = _make_client(handler, enabled=False)
        assert c.enviar(titulo="hola", cuerpo="ok") is None
        assert calls == []

    def test_publicacion_exitosa_devuelve_true(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        c = _make_client(handler, default_topic="custodiam-emergencias")
        assert c.enviar(titulo="hola", cuerpo="ok") is True

    def test_5xx_lanza_ntfy_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(502, text="bad gateway")

        c = _make_client(handler, default_topic="x")
        with pytest.raises(NtfyError):
            c.enviar(titulo="x", cuerpo="y")

    def test_topic_personalizado_se_usa_en_la_url(self):
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200)

        c = _make_client(handler, default_topic="default")
        c.enviar(titulo="x", cuerpo="y", topic="alertas-test")
        assert str(captured[0].url) == f"{BASE}/alertas-test"

    def test_default_topic_se_usa_si_no_se_especifica(self):
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200)

        c = _make_client(handler, default_topic="custodiam-emergencias")
        c.enviar(titulo="x", cuerpo="y")
        assert str(captured[0].url) == f"{BASE}/custodiam-emergencias"

    def test_mapeo_prioridad_critica_va_a_urgent(self):
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200)

        c = _make_client(handler, default_topic="x")
        c.enviar(
            titulo="EMERGENCIA",
            cuerpo="activacion",
            prioridad=PrioridadNotificacion.CRITICA,
        )
        assert captured[0].headers["Priority"] == "urgent"
        assert captured[0].headers["Title"] == "EMERGENCIA"

    def test_tags_se_serializan_separadas_por_coma(self):
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200)

        c = _make_client(handler, default_topic="x")
        c.enviar(
            titulo="x",
            cuerpo="y",
            tags=["emergencia", "rotating_light"],
        )
        assert captured[0].headers["Tags"] == "emergencia,rotating_light"

    def test_cuerpo_va_como_body_bytes(self):
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200)

        c = _make_client(handler, default_topic="x")
        c.enviar(titulo="x", cuerpo="Mensaje con ñ y acentos áéíóú")
        assert captured[0].content == "Mensaje con ñ y acentos áéíóú".encode()
