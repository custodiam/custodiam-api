"""Tests de `app.repositories.dispositivos` (Epic E06).

Cubre el patrón UPSERT por ``fcm_token``, el soft delete y las consultas
auxiliares que consume el fan-out de notificaciones desde
``servicios.convocar()``.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.dispositivo import Dispositivo, PlataformaDispositivo
from app.models.notificacion import PrioridadNotificacion, TipoNotificacion
from app.repositories import dispositivos as repo


@pytest.fixture
def otro_voluntario(make_voluntario):
    return make_voluntario(
        nombre="Beatriz Sanz", telefono="+34611111111", dni="22222222B"
    )


class TestUpsert:
    def test_token_nuevo_crea_fila_activa(self, db_session, voluntario):
        d = repo.upsert(
            db_session,
            voluntario_id=voluntario.id,
            fcm_token="token-abc",
            plataforma=PlataformaDispositivo.ANDROID,
        )

        assert d.id is not None
        assert d.voluntario_id == voluntario.id
        assert d.fcm_token == "token-abc"
        assert d.plataforma == PlataformaDispositivo.ANDROID
        assert d.activo is True

    def test_mismo_token_mismo_voluntario_es_idempotente(
        self, db_session, voluntario
    ):
        primero = repo.upsert(
            db_session,
            voluntario_id=voluntario.id,
            fcm_token="token-abc",
            plataforma=PlataformaDispositivo.ANDROID,
        )
        segundo = repo.upsert(
            db_session,
            voluntario_id=voluntario.id,
            fcm_token="token-abc",
            plataforma=PlataformaDispositivo.ANDROID,
        )

        assert primero.id == segundo.id
        # No debe haber otra fila con ese token.
        from sqlmodel import select

        rows = db_session.exec(
            select(Dispositivo).where(Dispositivo.fcm_token == "token-abc")
        ).all()
        assert len(rows) == 1

    def test_token_existente_inactivo_se_reactiva(
        self, db_session, voluntario
    ):
        d = repo.upsert(
            db_session,
            voluntario_id=voluntario.id,
            fcm_token="token-x",
            plataforma=PlataformaDispositivo.IOS,
        )
        repo.desactivar(db_session, d)

        reactivado = repo.upsert(
            db_session,
            voluntario_id=voluntario.id,
            fcm_token="token-x",
            plataforma=PlataformaDispositivo.IOS,
        )

        assert reactivado.id == d.id
        assert reactivado.activo is True

    def test_token_de_otro_voluntario_se_reasigna(
        self, db_session, voluntario, otro_voluntario
    ):
        primero = repo.upsert(
            db_session,
            voluntario_id=voluntario.id,
            fcm_token="token-shared",
            plataforma=PlataformaDispositivo.WEB,
        )

        reasignado = repo.upsert(
            db_session,
            voluntario_id=otro_voluntario.id,
            fcm_token="token-shared",
            plataforma=PlataformaDispositivo.WEB,
        )

        assert reasignado.id == primero.id
        assert reasignado.voluntario_id == otro_voluntario.id
        assert reasignado.activo is True


class TestListados:
    def test_list_activos_excluye_inactivos(self, db_session, voluntario):
        repo.upsert(
            db_session,
            voluntario_id=voluntario.id,
            fcm_token="t-1",
            plataforma=PlataformaDispositivo.ANDROID,
        )
        baja = repo.upsert(
            db_session,
            voluntario_id=voluntario.id,
            fcm_token="t-2",
            plataforma=PlataformaDispositivo.ANDROID,
        )
        repo.desactivar(db_session, baja)

        activos = repo.list_activos_por_voluntario(db_session, voluntario.id)
        assert [d.fcm_token for d in activos] == ["t-1"]

    def test_list_tokens_de_varios_voluntarios(
        self, db_session, voluntario, otro_voluntario
    ):
        repo.upsert(
            db_session,
            voluntario_id=voluntario.id,
            fcm_token="t-vol-1",
            plataforma=PlataformaDispositivo.ANDROID,
        )
        repo.upsert(
            db_session,
            voluntario_id=otro_voluntario.id,
            fcm_token="t-vol-2",
            plataforma=PlataformaDispositivo.WEB,
        )
        inactivo = repo.upsert(
            db_session,
            voluntario_id=voluntario.id,
            fcm_token="t-vol-3-baja",
            plataforma=PlataformaDispositivo.ANDROID,
        )
        repo.desactivar(db_session, inactivo)

        encontrados = repo.list_tokens_activos_de_voluntarios(
            db_session, [voluntario.id, otro_voluntario.id]
        )
        tokens = sorted(d.fcm_token for d in encontrados)
        assert tokens == ["t-vol-1", "t-vol-2"]

    def test_list_tokens_con_lista_vacia_devuelve_lista_vacia(self, db_session):
        assert repo.list_tokens_activos_de_voluntarios(db_session, []) == []

    def test_list_tokens_planos_extrae_solo_el_string(self):
        d1 = Dispositivo(
            voluntario_id=uuid.uuid4(),
            fcm_token="t-1",
            plataforma=PlataformaDispositivo.ANDROID,
        )
        d2 = Dispositivo(
            voluntario_id=uuid.uuid4(),
            fcm_token="t-2",
            plataforma=PlataformaDispositivo.IOS,
        )
        assert repo.list_tokens_planos([d1, d2]) == ["t-1", "t-2"]


class TestCrearNotificacion:
    def test_audit_log_sin_servicio(self, db_session):
        n = repo.crear_notificacion(
            db_session,
            tipo=TipoNotificacion.SISTEMA,
            prioridad=PrioridadNotificacion.NORMAL,
            titulo="Aviso",
            cuerpo="Mantenimiento programado",
        )

        assert n.id is not None
        assert n.servicio_id is None
        assert n.enviadas_count == 0
        assert n.entregadas_count == 0

    def test_audit_log_con_servicio_y_contadores(
        self, db_session, servicio_activo
    ):
        n = repo.crear_notificacion(
            db_session,
            tipo=TipoNotificacion.EMERGENCIA,
            prioridad=PrioridadNotificacion.CRITICA,
            titulo="EMERGENCIA",
            cuerpo="Activación",
            servicio_id=servicio_activo.id,
            enviadas_count=3,
            entregadas_count=2,
        )

        assert n.servicio_id == servicio_activo.id
        assert n.enviadas_count == 3
        assert n.entregadas_count == 2
