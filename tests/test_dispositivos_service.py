"""Tests de `app.services.dispositivos` (Epic E06)."""

from __future__ import annotations

import uuid

import pytest

from app.models.dispositivo import PlataformaDispositivo
from app.repositories import dispositivos as repo
from app.services import dispositivos as service


@pytest.fixture
def otro_voluntario(make_voluntario):
    return make_voluntario(
        nombre="Beatriz Sanz", telefono="+34611111111", dni="22222222B"
    )


class TestRegistrar:
    def test_registrar_devuelve_dispositivo_activo(self, db_session, voluntario):
        d = service.registrar(
            db_session,
            voluntario_id=voluntario.id,
            fcm_token="abc",
            plataforma=PlataformaDispositivo.ANDROID,
        )
        assert d.activo is True
        assert d.voluntario_id == voluntario.id

    def test_registrar_segunda_vez_no_duplica(self, db_session, voluntario):
        primero = service.registrar(
            db_session,
            voluntario_id=voluntario.id,
            fcm_token="abc",
            plataforma=PlataformaDispositivo.ANDROID,
        )
        segundo = service.registrar(
            db_session,
            voluntario_id=voluntario.id,
            fcm_token="abc",
            plataforma=PlataformaDispositivo.ANDROID,
        )
        assert primero.id == segundo.id


class TestListarPropios:
    def test_devuelve_solo_activos_del_voluntario(
        self, db_session, voluntario, otro_voluntario
    ):
        service.registrar(
            db_session,
            voluntario_id=voluntario.id,
            fcm_token="t-mio-activo",
            plataforma=PlataformaDispositivo.ANDROID,
        )
        inactivo = service.registrar(
            db_session,
            voluntario_id=voluntario.id,
            fcm_token="t-mio-baja",
            plataforma=PlataformaDispositivo.IOS,
        )
        repo.desactivar(db_session, inactivo)
        service.registrar(
            db_session,
            voluntario_id=otro_voluntario.id,
            fcm_token="t-otro",
            plataforma=PlataformaDispositivo.WEB,
        )

        mios = service.listar_propios(db_session, voluntario.id)
        assert [d.fcm_token for d in mios] == ["t-mio-activo"]


class TestDarBajaPropio:
    def test_dar_baja_propio_marca_inactivo(self, db_session, voluntario):
        d = service.registrar(
            db_session,
            voluntario_id=voluntario.id,
            fcm_token="t",
            plataforma=PlataformaDispositivo.ANDROID,
        )

        resultado = service.dar_baja_propio(
            db_session,
            dispositivo_id=d.id,
            voluntario_id_actual=voluntario.id,
        )

        assert resultado.activo is False

    def test_dar_baja_de_otro_voluntario_lanza_dominio_403(
        self, db_session, voluntario, otro_voluntario
    ):
        d = service.registrar(
            db_session,
            voluntario_id=otro_voluntario.id,
            fcm_token="t-ajeno",
            plataforma=PlataformaDispositivo.WEB,
        )

        with pytest.raises(service.DispositivoDeOtroVoluntario):
            service.dar_baja_propio(
                db_session,
                dispositivo_id=d.id,
                voluntario_id_actual=voluntario.id,
            )

    def test_dar_baja_id_inexistente_lanza_no_encontrado(
        self, db_session, voluntario
    ):
        with pytest.raises(service.DispositivoNoEncontrado):
            service.dar_baja_propio(
                db_session,
                dispositivo_id=uuid.uuid4(),
                voluntario_id_actual=voluntario.id,
            )
