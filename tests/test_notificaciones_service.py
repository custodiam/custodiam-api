"""Tests de `app.services.notificaciones` (Epic E06).

Cubre el fan-out FCM + ntfy, la clasificación por tipo de servicio, la
desactivación automática de tokens caducos y la resiliencia ante fallos
de los canales externos.
"""

from __future__ import annotations

import pytest

from app.models.dispositivo import PlataformaDispositivo
from app.models.notificacion import PrioridadNotificacion, TipoNotificacion
from app.models.servicio import TipoServicio
from app.repositories import dispositivos as repo_dispositivos
from app.services import notificaciones as service
from tests.conftest import FakeFcmAdmin, FakeNtfyClient


@pytest.fixture
def fcm() -> FakeFcmAdmin:
    return FakeFcmAdmin()


@pytest.fixture
def ntfy() -> FakeNtfyClient:
    return FakeNtfyClient()


@pytest.fixture
def voluntario_con_token(db_session, voluntario):
    repo_dispositivos.upsert(
        db_session,
        voluntario_id=voluntario.id,
        fcm_token="t-vol",
        plataforma=PlataformaDispositivo.ANDROID,
    )
    return voluntario


class TestClasificacion:
    def test_emergencia_es_critica(self, servicio_publicado):
        servicio_publicado.tipo = TipoServicio.EMERGENCIA
        tipo, prio = service._clasificar_servicio(servicio_publicado)
        assert tipo == TipoNotificacion.EMERGENCIA
        assert prio == PrioridadNotificacion.CRITICA

    def test_preventivo_es_normal(self, servicio_publicado):
        servicio_publicado.tipo = TipoServicio.PREVENTIVO
        tipo, prio = service._clasificar_servicio(servicio_publicado)
        assert tipo == TipoNotificacion.SERVICIO
        assert prio == PrioridadNotificacion.NORMAL

    def test_formacion_es_baja(self, servicio_publicado):
        servicio_publicado.tipo = TipoServicio.FORMACION
        tipo, prio = service._clasificar_servicio(servicio_publicado)
        assert tipo == TipoNotificacion.SERVICIO
        assert prio == PrioridadNotificacion.BAJA


class TestEmergencia:
    def test_emergencia_dispara_fcm_critica_y_ntfy(
        self, db_session, voluntario_con_token, make_servicio, fcm, ntfy
    ):
        servicio = make_servicio(tipo=TipoServicio.EMERGENCIA)

        notif = service.notificar_convocatoria(
            db_session,
            servicio=servicio,
            voluntario_ids=[voluntario_con_token.id],
            fcm_client=fcm,
            ntfy_client=ntfy,
        )

        assert len(fcm.envios) == 1
        envio = fcm.envios[0]
        assert envio["token"] == "t-vol"
        assert envio["prioridad"] == PrioridadNotificacion.CRITICA
        assert envio["data"] == {
            "servicio_id": str(servicio.id),
            "tipo": "emergencia",
        }
        assert envio["titulo"].startswith("EMERGENCIA:")

        assert len(ntfy.publicaciones) == 1
        assert ntfy.publicaciones[0]["topic"] == "custodiam-emergencias"
        assert ntfy.publicaciones[0]["prioridad"] == PrioridadNotificacion.CRITICA

        assert notif.tipo == TipoNotificacion.EMERGENCIA
        assert notif.prioridad == PrioridadNotificacion.CRITICA
        assert notif.servicio_id == servicio.id
        assert notif.enviadas_count == 2  # 1 FCM + 1 ntfy


class TestPreventivo:
    def test_preventivo_dispara_fcm_normal_sin_ntfy(
        self, db_session, voluntario_con_token, make_servicio, fcm, ntfy
    ):
        servicio = make_servicio(tipo=TipoServicio.PREVENTIVO)

        notif = service.notificar_convocatoria(
            db_session,
            servicio=servicio,
            voluntario_ids=[voluntario_con_token.id],
            fcm_client=fcm,
            ntfy_client=ntfy,
        )

        assert len(fcm.envios) == 1
        assert fcm.envios[0]["prioridad"] == PrioridadNotificacion.NORMAL
        assert ntfy.publicaciones == []
        assert notif.enviadas_count == 1


class TestResiliencia:
    def test_sin_dispositivos_no_envia_pero_si_audit_log(
        self, db_session, voluntario, make_servicio, fcm, ntfy
    ):
        servicio = make_servicio(tipo=TipoServicio.PREVENTIVO)

        notif = service.notificar_convocatoria(
            db_session,
            servicio=servicio,
            voluntario_ids=[voluntario.id],
            fcm_client=fcm,
            ntfy_client=ntfy,
        )

        assert fcm.envios == []
        assert notif.enviadas_count == 0
        assert notif.servicio_id == servicio.id

    def test_token_caducado_marca_dispositivo_inactivo(
        self, db_session, voluntario, make_servicio, ntfy
    ):
        d = repo_dispositivos.upsert(
            db_session,
            voluntario_id=voluntario.id,
            fcm_token="caduco",
            plataforma=PlataformaDispositivo.ANDROID,
        )
        fcm_que_marca_invalido = FakeFcmAdmin(tokens_invalidos={"caduco"})
        servicio = make_servicio(tipo=TipoServicio.PREVENTIVO)

        notif = service.notificar_convocatoria(
            db_session,
            servicio=servicio,
            voluntario_ids=[voluntario.id],
            fcm_client=fcm_que_marca_invalido,
            ntfy_client=ntfy,
        )

        assert notif.enviadas_count == 0
        recargado = repo_dispositivos.get(db_session, d.id)
        assert recargado is not None
        assert recargado.activo is False

    def test_fallo_5xx_de_fcm_no_rompe_audit_log(
        self, db_session, voluntario_con_token, make_servicio, ntfy
    ):
        fcm_caido = FakeFcmAdmin(tokens_5xx={"t-vol"})
        servicio = make_servicio(tipo=TipoServicio.PREVENTIVO)

        notif = service.notificar_convocatoria(
            db_session,
            servicio=servicio,
            voluntario_ids=[voluntario_con_token.id],
            fcm_client=fcm_caido,
            ntfy_client=ntfy,
        )

        # No se contabiliza el envío fallido, pero la fila de audit
        # existe (intent registrado).
        assert notif.enviadas_count == 0
        assert notif.servicio_id == servicio.id

    def test_fallo_5xx_de_ntfy_no_rompe_audit_ni_fcm(
        self, db_session, voluntario_con_token, make_servicio, fcm
    ):
        ntfy_caido = FakeNtfyClient(fail=True)
        servicio = make_servicio(tipo=TipoServicio.EMERGENCIA)

        notif = service.notificar_convocatoria(
            db_session,
            servicio=servicio,
            voluntario_ids=[voluntario_con_token.id],
            fcm_client=fcm,
            ntfy_client=ntfy_caido,
        )

        # FCM sí se envió aunque ntfy fallara.
        assert len(fcm.envios) == 1
        assert notif.enviadas_count == 1  # solo FCM cuenta

    def test_clientes_deshabilitados_solo_persisten_audit_log(
        self, db_session, voluntario_con_token, make_servicio
    ):
        fcm_off = FakeFcmAdmin(enabled=False)
        ntfy_off = FakeNtfyClient(enabled=False)
        servicio = make_servicio(tipo=TipoServicio.EMERGENCIA)

        notif = service.notificar_convocatoria(
            db_session,
            servicio=servicio,
            voluntario_ids=[voluntario_con_token.id],
            fcm_client=fcm_off,
            ntfy_client=ntfy_off,
        )

        assert fcm_off.envios == []
        assert ntfy_off.publicaciones == []
        assert notif.enviadas_count == 0
        # El audit log se conserva: el intento está registrado.
        assert notif.servicio_id == servicio.id
