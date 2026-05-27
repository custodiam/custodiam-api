"""Tests del router del historial del voluntario (EN-02-04 / US-02-06)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.models.fichaje import Fichaje
from app.models.inscripcion_servicio import InscripcionServicio, TipoInscripcion
from app.models.servicio import EstadoServicio
from app.models.voluntario_evento import TipoEventoVoluntario
from app.repositories import voluntario_evento as repo

API_HISTORIAL = "/api/v1/voluntarios/me/historial"
API_RESUMEN = "/api/v1/voluntarios/me/resumen"


@pytest.fixture
def yo(make_voluntario):
    return make_voluntario(keycloak_id="test-user-id")


class TestHistorialEndpoint:
    def test_historial_vacio(self, authenticated_client: TestClient, db_session, yo):
        response = authenticated_client.get(API_HISTORIAL)
        assert response.status_code == 200
        assert response.json() == []
        assert response.headers["X-Total-Count"] == "0"

    def test_lista_devuelve_eventos_mios_mas_reciente_primero(
        self, authenticated_client: TestClient, db_session, yo
    ):
        primero = repo.registrar(
            db_session,
            voluntario_id=yo.id,
            tipo=TipoEventoVoluntario.ALTA,
        )
        segundo = repo.registrar(
            db_session,
            voluntario_id=yo.id,
            tipo=TipoEventoVoluntario.CAMBIO_ROL_ASIGNADO,
            payload={"rol_nombre": "voluntario"},
        )

        response = authenticated_client.get(API_HISTORIAL)
        assert response.status_code == 200
        body = response.json()
        ids = [e["id"] for e in body]
        assert ids == [str(segundo.id), str(primero.id)]
        # El payload JSONB se serializa correctamente.
        assert body[0]["payload"] == {"rol_nombre": "voluntario"}

    def test_filtro_por_tipo_repetido(
        self, authenticated_client: TestClient, db_session, yo
    ):
        repo.registrar(
            db_session,
            voluntario_id=yo.id,
            tipo=TipoEventoVoluntario.FICHAJE_ENTRADA,
        )
        repo.registrar(
            db_session,
            voluntario_id=yo.id,
            tipo=TipoEventoVoluntario.FICHAJE_SALIDA,
        )
        repo.registrar(
            db_session,
            voluntario_id=yo.id,
            tipo=TipoEventoVoluntario.ALTA,
        )

        response = authenticated_client.get(
            f"{API_HISTORIAL}?tipo=fichaje_entrada&tipo=fichaje_salida"
        )
        assert response.status_code == 200
        tipos = {e["tipo_evento"] for e in response.json()}
        assert tipos == {"fichaje_entrada", "fichaje_salida"}
        assert response.headers["X-Total-Count"] == "2"

    def test_paginacion_con_x_total_count(
        self, authenticated_client: TestClient, db_session, yo
    ):
        for _ in range(7):
            repo.registrar(
                db_session,
                voluntario_id=yo.id,
                tipo=TipoEventoVoluntario.FICHAJE_ENTRADA,
            )

        response = authenticated_client.get(f"{API_HISTORIAL}?skip=2&limit=3")
        assert response.status_code == 200
        assert len(response.json()) == 3
        assert response.headers["X-Total-Count"] == "7"

    def test_since_until_son_aceptados(
        self, authenticated_client: TestClient, db_session, yo
    ):
        repo.registrar(
            db_session,
            voluntario_id=yo.id,
            tipo=TipoEventoVoluntario.ALTA,
        )
        futuro = (datetime.now() + timedelta(days=1)).isoformat()
        response = authenticated_client.get(f"{API_HISTORIAL}?since={futuro}")
        assert response.status_code == 200
        assert response.json() == []
        assert response.headers["X-Total-Count"] == "0"

    def test_sin_voluntario_devuelve_404(self, authenticated_client: TestClient):
        response = authenticated_client.get(API_HISTORIAL)
        assert response.status_code == 404

    def test_sin_autenticacion_devuelve_401(self, client: TestClient):
        response = client.get(API_HISTORIAL)
        assert response.status_code == 401

    def test_admin_puro_recibe_403(self, client_for_role):
        c = client_for_role(roles=["admin"], sub="user-admin")
        response = c.get(API_HISTORIAL)
        assert response.status_code == 403


class TestResumenEndpoint:
    def test_resumen_vacio_devuelve_ceros(
        self, authenticated_client: TestClient, db_session, yo
    ):
        response = authenticated_client.get(API_RESUMEN)
        assert response.status_code == 200
        body = response.json()
        assert body["horas_totales"] == 0
        assert body["segundos_totales"] == 0
        assert body["servicios_realizados"] == 0
        assert body["ultimo_servicio"] is None

    def test_resumen_con_actividad_real(
        self,
        authenticated_client: TestClient,
        db_session,
        yo,
        make_servicio,
    ):
        servicio = make_servicio(
            estado=EstadoServicio.CERRADO,
            titulo="Carrera popular",
            fecha_inicio=datetime(2026, 4, 1, 9, 0),
        )
        db_session.add(
            Fichaje(
                servicio_id=servicio.id,
                voluntario_id=yo.id,
                hora_entrada=datetime(2026, 4, 1, 9, 0),
                hora_salida=datetime(2026, 4, 1, 12, 30),
                automatico=False,
            )
        )
        db_session.add(
            InscripcionServicio(
                servicio_id=servicio.id,
                voluntario_id=yo.id,
                tipo=TipoInscripcion.CONVOCADO,
                fecha=datetime(2026, 4, 1, 8, 0),
            )
        )
        db_session.commit()

        response = authenticated_client.get(API_RESUMEN)
        assert response.status_code == 200
        body = response.json()
        # 3h30m = 12600 segundos → 3 horas redondeadas hacia abajo.
        assert body["segundos_totales"] == 12600
        assert body["horas_totales"] == 3
        assert body["servicios_realizados"] == 1
        assert body["ultimo_servicio"]["titulo"] == "Carrera popular"
        assert body["ultimo_servicio"]["servicio_id"] == str(servicio.id)

    def test_resumen_sin_voluntario_404(self, authenticated_client: TestClient):
        response = authenticated_client.get(API_RESUMEN)
        assert response.status_code == 404
