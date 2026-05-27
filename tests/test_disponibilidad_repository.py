"""Tests de `app.repositories.disponibilidad` (US-02-04 / CU-12).

Cubre el UPSERT por (voluntario_id, fecha), las consultas mensuales con
rango inclusivo en sus dos extremos y la idempotencia del UPSERT cuando
se repite la operación.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.repositories import disponibilidad as repo


@pytest.fixture
def otro_voluntario(make_voluntario):
    return make_voluntario(
        nombre="Beatriz Sanz", telefono="+34611111111", dni="22222222B"
    )


class TestUpsert:
    def test_dia_nuevo_crea_fila(self, db_session, voluntario):
        d = repo.upsert_dia(
            db_session,
            voluntario_id=voluntario.id,
            fecha=date(2026, 6, 1),
            disponible=True,
        )
        assert d.id is not None
        assert d.voluntario_id == voluntario.id
        assert d.fecha == date(2026, 6, 1)
        assert d.disponible is True

    def test_dia_existente_se_actualiza_sin_duplicar(self, db_session, voluntario):
        primero = repo.upsert_dia(
            db_session,
            voluntario_id=voluntario.id,
            fecha=date(2026, 6, 1),
            disponible=True,
        )
        segundo = repo.upsert_dia(
            db_session,
            voluntario_id=voluntario.id,
            fecha=date(2026, 6, 1),
            disponible=False,
        )

        assert primero.id == segundo.id
        assert segundo.disponible is False

    def test_voluntarios_distintos_no_se_pisan(
        self, db_session, voluntario, otro_voluntario
    ):
        repo.upsert_dia(
            db_session,
            voluntario_id=voluntario.id,
            fecha=date(2026, 6, 1),
            disponible=True,
        )
        repo.upsert_dia(
            db_session,
            voluntario_id=otro_voluntario.id,
            fecha=date(2026, 6, 1),
            disponible=False,
        )

        mio = repo.get_by_voluntario_y_fecha(
            db_session, voluntario_id=voluntario.id, fecha=date(2026, 6, 1)
        )
        suyo = repo.get_by_voluntario_y_fecha(
            db_session,
            voluntario_id=otro_voluntario.id,
            fecha=date(2026, 6, 1),
        )
        assert mio is not None and mio.disponible is True
        assert suyo is not None and suyo.disponible is False


class TestListMes:
    def test_mes_vacio_devuelve_lista_vacia(self, db_session, voluntario):
        resultado = repo.list_by_voluntario_mes(
            db_session, voluntario_id=voluntario.id, year=2026, month=6
        )
        assert resultado == []

    def test_solo_filas_del_mes_pedido(self, db_session, voluntario):
        repo.upsert_dia(
            db_session,
            voluntario_id=voluntario.id,
            fecha=date(2026, 5, 31),
            disponible=True,
        )
        repo.upsert_dia(
            db_session,
            voluntario_id=voluntario.id,
            fecha=date(2026, 6, 1),
            disponible=True,
        )
        repo.upsert_dia(
            db_session,
            voluntario_id=voluntario.id,
            fecha=date(2026, 6, 30),
            disponible=False,
        )
        repo.upsert_dia(
            db_session,
            voluntario_id=voluntario.id,
            fecha=date(2026, 7, 1),
            disponible=True,
        )

        junio = repo.list_by_voluntario_mes(
            db_session, voluntario_id=voluntario.id, year=2026, month=6
        )
        assert [d.fecha for d in junio] == [date(2026, 6, 1), date(2026, 6, 30)]

    def test_febrero_bisiesto_incluye_dia_29(self, db_session, voluntario):
        # 2028 es bisiesto: 29 de febrero existe.
        repo.upsert_dia(
            db_session,
            voluntario_id=voluntario.id,
            fecha=date(2028, 2, 29),
            disponible=True,
        )
        febrero = repo.list_by_voluntario_mes(
            db_session, voluntario_id=voluntario.id, year=2028, month=2
        )
        assert [d.fecha for d in febrero] == [date(2028, 2, 29)]

    def test_filtra_por_voluntario(self, db_session, voluntario, otro_voluntario):
        repo.upsert_dia(
            db_session,
            voluntario_id=voluntario.id,
            fecha=date(2026, 6, 1),
            disponible=True,
        )
        repo.upsert_dia(
            db_session,
            voluntario_id=otro_voluntario.id,
            fecha=date(2026, 6, 2),
            disponible=True,
        )

        mio = repo.list_by_voluntario_mes(
            db_session, voluntario_id=voluntario.id, year=2026, month=6
        )
        assert [d.fecha for d in mio] == [date(2026, 6, 1)]


class TestGetByFecha:
    def test_devuelve_none_si_no_existe(self, db_session, voluntario):
        resultado = repo.get_by_voluntario_y_fecha(
            db_session, voluntario_id=voluntario.id, fecha=date(2026, 6, 1)
        )
        assert resultado is None

    def test_devuelve_la_fila_si_existe(self, db_session, voluntario):
        repo.upsert_dia(
            db_session,
            voluntario_id=voluntario.id,
            fecha=date(2026, 6, 1),
            disponible=True,
        )
        resultado = repo.get_by_voluntario_y_fecha(
            db_session, voluntario_id=voluntario.id, fecha=date(2026, 6, 1)
        )
        assert resultado is not None
        assert resultado.disponible is True
