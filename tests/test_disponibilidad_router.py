"""Tests del router `/api/v1/voluntarios/me/disponibilidad` (US-02-04 / CU-12).

Cubre los dos endpoints, el RBAC y los códigos de error 401/404/422.
La fecha de "hoy" para los tests del PUT se controla con un override
del helper interno del service para que el caso "fecha pasada" sea
determinístico independientemente de la fecha del sistema.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.repositories import disponibilidad as repo
from app.services import disponibilidad as service

API = "/api/v1/voluntarios/me/disponibilidad"


@pytest.fixture
def yo(make_voluntario):
    """Voluntario vinculado al ``sub`` del cliente autenticado por defecto."""

    return make_voluntario(keycloak_id="test-user-id")


@pytest.fixture
def fecha_referencia(monkeypatch):
    """Congela ``date.today()`` a 2026-05-28 para los tests del PUT."""

    hoy = date(2026, 5, 28)

    class _FakeDate(date):
        @classmethod
        def today(cls) -> date:  # type: ignore[override]
            return hoy

    monkeypatch.setattr(service, "date", _FakeDate)
    return hoy


class TestObtenerMes:
    def test_mes_vacio_devuelve_estructura_con_lista_vacia(
        self, authenticated_client: TestClient, db_session, yo
    ):
        response = authenticated_client.get(f"{API}?year=2026&month=6")
        assert response.status_code == 200
        body = response.json()
        assert body["year"] == 2026
        assert body["month"] == 6
        assert body["dias"] == []

    def test_mes_con_filas_devuelve_lista_ordenada(
        self, authenticated_client: TestClient, db_session, yo
    ):
        repo.upsert_dia(
            db_session,
            voluntario_id=yo.id,
            fecha=date(2026, 6, 15),
            disponible=True,
        )
        repo.upsert_dia(
            db_session,
            voluntario_id=yo.id,
            fecha=date(2026, 6, 1),
            disponible=False,
        )
        response = authenticated_client.get(f"{API}?year=2026&month=6")
        assert response.status_code == 200
        fechas = [d["fecha"] for d in response.json()["dias"]]
        assert fechas == ["2026-06-01", "2026-06-15"]

    def test_query_params_obligatorios(self, authenticated_client: TestClient, yo):
        response = authenticated_client.get(API)
        # Faltan year/month → 422 de FastAPI.
        assert response.status_code == 422

    def test_year_fuera_de_rango_es_422(self, authenticated_client: TestClient, yo):
        response = authenticated_client.get(f"{API}?year=1999&month=6")
        assert response.status_code == 422

    def test_sin_voluntario_en_bd_devuelve_404_amigable(
        self, authenticated_client: TestClient
    ):
        response = authenticated_client.get(f"{API}?year=2026&month=6")
        assert response.status_code == 404
        assert "administrador" in response.json()["detail"]

    def test_sin_autenticacion_devuelve_401(self, client: TestClient):
        response = client.get(f"{API}?year=2026&month=6")
        assert response.status_code == 401


class TestMarcarDia:
    def test_marca_dia_futuro_devuelve_200(
        self,
        authenticated_client: TestClient,
        db_session,
        yo,
        fecha_referencia,
    ):
        response = authenticated_client.put(
            f"{API}/2027-06-15",
            json={"disponible": True},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["voluntario_id"] == str(yo.id)
        assert body["fecha"] == "2027-06-15"
        assert body["disponible"] is True

    def test_marca_es_idempotente(
        self,
        authenticated_client: TestClient,
        db_session,
        yo,
        fecha_referencia,
    ):
        primero = authenticated_client.put(
            f"{API}/2027-06-15",
            json={"disponible": True},
        )
        segundo = authenticated_client.put(
            f"{API}/2027-06-15",
            json={"disponible": False},
        )
        assert primero.status_code == 200
        assert segundo.status_code == 200
        assert primero.json()["id"] == segundo.json()["id"]
        assert segundo.json()["disponible"] is False

    def test_fecha_pasada_devuelve_422(
        self,
        authenticated_client: TestClient,
        db_session,
        yo,
        fecha_referencia,
    ):
        response = authenticated_client.put(
            f"{API}/2026-05-27",
            json={"disponible": True},
        )
        assert response.status_code == 422
        assert "anterior" in response.json()["detail"]

    def test_fecha_mal_formada_devuelve_422(
        self, authenticated_client: TestClient, yo
    ):
        response = authenticated_client.put(
            f"{API}/no-es-fecha",
            json={"disponible": True},
        )
        assert response.status_code == 422

    def test_body_sin_disponible_devuelve_422(
        self, authenticated_client: TestClient, yo
    ):
        response = authenticated_client.put(
            f"{API}/2027-06-15",
            json={},
        )
        assert response.status_code == 422

    def test_sin_voluntario_en_bd_devuelve_404(
        self, authenticated_client: TestClient, fecha_referencia
    ):
        response = authenticated_client.put(
            f"{API}/2027-06-15",
            json={"disponible": True},
        )
        assert response.status_code == 404
        assert "administrador" in response.json()["detail"]

    def test_admin_puro_sin_permiso_disponibilidad_recibe_403(
        self,
        client_for_role,
        db_session,
        make_voluntario,
        fecha_referencia,
    ):
        # admin (técnico puro, sin coordinador) NO tiene voluntarios.disponibilidad_propia.
        # El fixture admin_client mezcla admin + coordinador, así que aquí
        # usamos client_for_role para aislar la matriz RBAC del admin solo.
        make_voluntario(keycloak_id="user-admin")
        c = client_for_role(roles=["admin"], sub="user-admin")
        response = c.put(
            f"{API}/2027-06-15",
            json={"disponible": True},
        )
        assert response.status_code == 403

    def test_admin_puro_sin_permiso_ver_propio_recibe_403_en_get(
        self, client_for_role
    ):
        c = client_for_role(roles=["admin"], sub="user-admin")
        response = c.get(f"{API}?year=2026&month=6")
        assert response.status_code == 403
