"""Tests de `app.services.disponibilidad` (US-02-04 / CU-12)."""

from __future__ import annotations

from datetime import date

import pytest

from app.repositories import disponibilidad as repo
from app.services import disponibilidad as service
from app.services.voluntarios import VoluntarioNoEncontrado


@pytest.fixture
def yo(make_voluntario):
    """Voluntario vinculado al ``sub`` de un cliente fake autenticado."""

    return make_voluntario(keycloak_id="kc-yo")


class TestObtenerMiMes:
    def test_mes_vacio_devuelve_lista_vacia(self, db_session, yo):
        resultado = service.obtener_mi_mes(
            db_session, keycloak_id="kc-yo", year=2026, month=6
        )
        assert resultado == []

    def test_devuelve_solo_filas_propias_del_mes(self, db_session, yo):
        repo.upsert_dia(
            db_session,
            voluntario_id=yo.id,
            fecha=date(2026, 6, 15),
            disponible=True,
        )
        repo.upsert_dia(
            db_session,
            voluntario_id=yo.id,
            fecha=date(2026, 7, 1),
            disponible=True,
        )
        junio = service.obtener_mi_mes(
            db_session, keycloak_id="kc-yo", year=2026, month=6
        )
        assert [d.fecha for d in junio] == [date(2026, 6, 15)]

    def test_keycloak_id_sin_voluntario_lanza_no_encontrado(self, db_session):
        with pytest.raises(VoluntarioNoEncontrado):
            service.obtener_mi_mes(
                db_session, keycloak_id="kc-no-existe", year=2026, month=6
            )

    def test_mes_fuera_de_rango_lanza_mes_invalido(self, db_session, yo):
        with pytest.raises(service.MesInvalido):
            service.obtener_mi_mes(
                db_session, keycloak_id="kc-yo", year=2026, month=13
            )


class TestMarcarDia:
    def test_marca_dia_futuro(self, db_session, yo):
        # Fecha futura por construcción (>= 2027).
        d = service.marcar_dia(
            db_session,
            keycloak_id="kc-yo",
            fecha=date(2027, 6, 15),
            disponible=True,
            hoy=date(2026, 5, 28),
        )
        assert d.voluntario_id == yo.id
        assert d.disponible is True

    def test_marca_hoy_se_permite(self, db_session, yo):
        hoy = date(2026, 5, 28)
        d = service.marcar_dia(
            db_session,
            keycloak_id="kc-yo",
            fecha=hoy,
            disponible=True,
            hoy=hoy,
        )
        assert d.fecha == hoy

    def test_marca_fecha_pasada_se_rechaza(self, db_session, yo):
        with pytest.raises(service.FechaPasada):
            service.marcar_dia(
                db_session,
                keycloak_id="kc-yo",
                fecha=date(2026, 5, 27),
                disponible=True,
                hoy=date(2026, 5, 28),
            )

    def test_marcar_es_idempotente(self, db_session, yo):
        primero = service.marcar_dia(
            db_session,
            keycloak_id="kc-yo",
            fecha=date(2027, 6, 1),
            disponible=True,
            hoy=date(2026, 5, 28),
        )
        segundo = service.marcar_dia(
            db_session,
            keycloak_id="kc-yo",
            fecha=date(2027, 6, 1),
            disponible=False,
            hoy=date(2026, 5, 28),
        )
        assert primero.id == segundo.id
        assert segundo.disponible is False

    def test_keycloak_id_sin_voluntario_lanza_no_encontrado(self, db_session):
        with pytest.raises(VoluntarioNoEncontrado):
            service.marcar_dia(
                db_session,
                keycloak_id="kc-no-existe",
                fecha=date(2027, 6, 1),
                disponible=True,
                hoy=date(2026, 5, 28),
            )
