"""Tests del Repository de fichajes (EN-04-02)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.models.fichaje import Fichaje
from app.repositories import fichajes as repo


class TestGet:
    def test_get_devuelve_none_si_no_existe(self, db_session):
        assert repo.get(db_session, uuid.uuid4()) is None

    def test_get_por_servicio_y_voluntario_inexistente(
        self, db_session, servicio_activo, voluntario
    ):
        assert (
            repo.get_por_servicio_y_voluntario(
                db_session,
                servicio_id=servicio_activo.id,
                voluntario_id=voluntario.id,
            )
            is None
        )


class TestCreate:
    def test_create_persiste_fichaje_abierto(
        self, db_session, servicio_activo, voluntario
    ):
        f = repo.create(
            db_session,
            data=dict(
                servicio_id=servicio_activo.id,
                voluntario_id=voluntario.id,
                hora_entrada=datetime(2026, 6, 1, 9, 0),
                hora_salida=None,
                automatico=False,
            ),
        )
        assert f.id is not None
        assert f.hora_salida is None
        assert f.automatico is False

    def test_get_por_servicio_y_voluntario_lo_localiza(
        self, db_session, servicio_activo, voluntario
    ):
        repo.create(
            db_session,
            data=dict(
                servicio_id=servicio_activo.id,
                voluntario_id=voluntario.id,
                hora_entrada=datetime(2026, 6, 1, 9, 0),
                hora_salida=None,
                automatico=False,
            ),
        )
        encontrado = repo.get_por_servicio_y_voluntario(
            db_session,
            servicio_id=servicio_activo.id,
            voluntario_id=voluntario.id,
        )
        assert encontrado is not None


class TestUpdate:
    def test_update_setea_hora_salida(
        self, db_session, servicio_activo, voluntario
    ):
        f = repo.create(
            db_session,
            data=dict(
                servicio_id=servicio_activo.id,
                voluntario_id=voluntario.id,
                hora_entrada=datetime(2026, 6, 1, 9, 0),
                hora_salida=None,
                automatico=False,
            ),
        )
        actualizado = repo.update(
            db_session, f, data={"hora_salida": datetime(2026, 6, 1, 14, 30)}
        )
        assert actualizado.hora_salida == datetime(2026, 6, 1, 14, 30)
        assert actualizado.duracion_segundos == 5 * 3600 + 30 * 60


class TestList:
    def test_list_por_servicio_ordenado_por_hora_entrada(
        self, db_session, servicio_activo, make_voluntario
    ):
        ana = make_voluntario(nombre="Ana")
        beatriz = make_voluntario(nombre="Beatriz")
        # Bea llega primero, Ana después.
        repo.create(
            db_session,
            data=dict(
                servicio_id=servicio_activo.id,
                voluntario_id=beatriz.id,
                hora_entrada=datetime(2026, 6, 1, 9, 0),
                hora_salida=None,
                automatico=False,
            ),
        )
        repo.create(
            db_session,
            data=dict(
                servicio_id=servicio_activo.id,
                voluntario_id=ana.id,
                hora_entrada=datetime(2026, 6, 1, 9, 5),
                hora_salida=None,
                automatico=False,
            ),
        )
        pares = repo.list_por_servicio(db_session, servicio_activo.id)
        nombres = [v.nombre for v, _ in pares]
        assert nombres == ["Beatriz", "Ana"]

    def test_list_por_voluntario_ordenado_descendente(
        self, db_session, voluntario, make_servicio
    ):
        s1 = make_servicio(titulo="Antiguo")
        s2 = make_servicio(titulo="Reciente")
        repo.create(
            db_session,
            data=dict(
                servicio_id=s1.id,
                voluntario_id=voluntario.id,
                hora_entrada=datetime(2026, 5, 1, 9, 0),
                hora_salida=None,
                automatico=False,
            ),
        )
        repo.create(
            db_session,
            data=dict(
                servicio_id=s2.id,
                voluntario_id=voluntario.id,
                hora_entrada=datetime(2026, 6, 1, 9, 0),
                hora_salida=None,
                automatico=False,
            ),
        )
        fichajes = repo.list_por_voluntario(db_session, voluntario.id)
        fechas = [f.hora_entrada for f in fichajes]
        assert fechas == sorted(fechas, reverse=True)

    def test_list_abiertos_por_servicio_filtra(
        self, db_session, servicio_activo, make_voluntario
    ):
        ana = make_voluntario(nombre="Ana")
        beatriz = make_voluntario(nombre="Beatriz")
        # Ana sigue abierta, Bea cerró.
        repo.create(
            db_session,
            data=dict(
                servicio_id=servicio_activo.id,
                voluntario_id=ana.id,
                hora_entrada=datetime(2026, 6, 1, 9, 0),
                hora_salida=None,
                automatico=False,
            ),
        )
        repo.create(
            db_session,
            data=dict(
                servicio_id=servicio_activo.id,
                voluntario_id=beatriz.id,
                hora_entrada=datetime(2026, 6, 1, 9, 5),
                hora_salida=datetime(2026, 6, 1, 13, 0),
                automatico=False,
            ),
        )
        abiertos = repo.list_abiertos_por_servicio(
            db_session, servicio_activo.id
        )
        assert len(abiertos) == 1
        assert abiertos[0].voluntario_id == ana.id


class TestHorasAcumuladas:
    def test_sin_fichajes_devuelve_ceros(self, db_session, voluntario):
        total_seg, n_cerrados, n_abiertos = repo.horas_acumuladas(
            db_session, voluntario.id
        )
        assert total_seg == 0
        assert n_cerrados == 0
        assert n_abiertos == 0

    def test_solo_cerrados_cuentan_para_horas(
        self, db_session, voluntario, make_servicio
    ):
        s1 = make_servicio()
        s2 = make_servicio()
        # Cerrado: 2 horas.
        repo.create(
            db_session,
            data=dict(
                servicio_id=s1.id,
                voluntario_id=voluntario.id,
                hora_entrada=datetime(2026, 6, 1, 9, 0),
                hora_salida=datetime(2026, 6, 1, 11, 0),
                automatico=False,
            ),
        )
        # Abierto.
        repo.create(
            db_session,
            data=dict(
                servicio_id=s2.id,
                voluntario_id=voluntario.id,
                hora_entrada=datetime(2026, 6, 2, 9, 0),
                hora_salida=None,
                automatico=False,
            ),
        )
        total_seg, n_cerrados, n_abiertos = repo.horas_acumuladas(
            db_session, voluntario.id
        )
        assert total_seg == 2 * 3600
        assert n_cerrados == 1
        assert n_abiertos == 1


def test_unique_constraint_servicio_voluntario(
    db_session, servicio_activo, voluntario
):
    """No se pueden crear dos fichajes para el mismo par."""

    db_session.add(
        Fichaje(
            servicio_id=servicio_activo.id,
            voluntario_id=voluntario.id,
            hora_entrada=datetime(2026, 6, 1, 9, 0),
            automatico=False,
        )
    )
    db_session.commit()
    db_session.add(
        Fichaje(
            servicio_id=servicio_activo.id,
            voluntario_id=voluntario.id,
            hora_entrada=datetime(2026, 6, 1, 9, 5),
            automatico=False,
        )
    )
    with pytest.raises(Exception):  # IntegrityError
        db_session.commit()
    db_session.rollback()


def test_duracion_segundos_property(
    db_session, servicio_activo, voluntario
):
    f = repo.create(
        db_session,
        data=dict(
            servicio_id=servicio_activo.id,
            voluntario_id=voluntario.id,
            hora_entrada=datetime(2026, 6, 1, 9, 0),
            hora_salida=datetime(2026, 6, 1, 9, 0) + timedelta(hours=3),
            automatico=False,
        ),
    )
    assert f.duracion_segundos == 3 * 3600
