"""Test cross-feature: `servicios.convocar` dispara el fan-out E06.

Verifica el contrato entre `services/servicios.py` y
`services/notificaciones.py` cuando se inyectan los clientes FCM y
ntfy en la llamada de convocatoria. No mockea a nivel de repository:
la inserción de Notificacion en BD también se verifica. Convocar solo
notifica y activa: no crea inscripciones (decisión del PO), de modo que
estos tests comprueban el envío y la transición de estado, no filas de
inscripción.
"""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.models.dispositivo import PlataformaDispositivo
from app.models.notificacion import Notificacion, PrioridadNotificacion
from app.models.servicio import EstadoServicio, TipoServicio
from app.repositories import dispositivos as repo_dispositivos
from app.services import servicios as servicio_service
from tests.conftest import FakeFcmAdmin, FakeNtfyClient


@pytest.fixture
def fcm() -> FakeFcmAdmin:
    return FakeFcmAdmin()


@pytest.fixture
def ntfy() -> FakeNtfyClient:
    return FakeNtfyClient()


@pytest.fixture
def vol_con_dispositivo(db_session, make_voluntario):
    v = make_voluntario(
        nombre="Carla Ruiz", telefono="+34622222222", dni="33333333C"
    )
    repo_dispositivos.upsert(
        db_session,
        voluntario_id=v.id,
        fcm_token=f"tok-{v.id}",
        plataforma=PlataformaDispositivo.ANDROID,
    )
    return v


class TestConvocarEmergencia:
    def test_emergencia_borrador_a_activo_envia_critica_y_ntfy(
        self,
        db_session,
        vol_con_dispositivo,
        make_servicio,
        fcm,
        ntfy,
    ):
        # Una emergencia recién creada arranca en BORRADOR/ACTIVO según
        # el service; aquí forzamos BORRADOR para verificar el salto
        # directo a ACTIVO permitido a las emergencias.
        servicio = make_servicio(
            tipo=TipoServicio.EMERGENCIA,
            estado=EstadoServicio.BORRADOR,
            titulo="Riada en Zaragoza",
            ubicacion="Pinares de Venecia",
        )

        servicio_devuelto = servicio_service.convocar(
            db_session,
            servicio.id,
            voluntario_ids=[vol_con_dispositivo.id],
            fcm_client=fcm,
            ntfy_client=ntfy,
        )

        assert servicio_devuelto.estado == EstadoServicio.ACTIVO

        # FCM: un envío crítico al token del voluntario.
        assert len(fcm.envios) == 1
        envio = fcm.envios[0]
        assert envio["token"] == f"tok-{vol_con_dispositivo.id}"
        assert envio["prioridad"] == PrioridadNotificacion.CRITICA
        assert "Riada en Zaragoza" in envio["titulo"]

        # ntfy: una publicación crítica.
        assert len(ntfy.publicaciones) == 1
        assert ntfy.publicaciones[0]["topic"] == "custodiam-emergencias"

        # Audit log: una fila en `notificaciones`.
        notifs = db_session.exec(select(Notificacion)).all()
        assert len(notifs) == 1
        assert notifs[0].servicio_id == servicio.id
        assert notifs[0].enviadas_count == 2  # 1 FCM + 1 ntfy


class TestConvocarPreventivo:
    def test_preventivo_publicado_a_activo_solo_fcm_normal(
        self,
        db_session,
        vol_con_dispositivo,
        make_servicio,
        fcm,
        ntfy,
    ):
        servicio = make_servicio(
            tipo=TipoServicio.PREVENTIVO,
            estado=EstadoServicio.PUBLICADO,
            titulo="Carrera benéfica",
        )

        servicio_service.convocar(
            db_session,
            servicio.id,
            voluntario_ids=[vol_con_dispositivo.id],
            fcm_client=fcm,
            ntfy_client=ntfy,
        )

        assert len(fcm.envios) == 1
        assert fcm.envios[0]["prioridad"] == PrioridadNotificacion.NORMAL

        # ntfy reservado a emergencias.
        assert ntfy.publicaciones == []


class TestRetrocompatibilidadSinClientes:
    def test_convocar_sin_clientes_no_persiste_audit_log_ni_envia(
        self,
        db_session,
        vol_con_dispositivo,
        make_servicio,
    ):
        """Asegura que los tests existentes (sin inyectar fcm/ntfy)
        siguen pasando: si los dos clientes son None, la convocatoria
        no toca el subsistema de notificaciones."""

        servicio = make_servicio(
            tipo=TipoServicio.PREVENTIVO,
            estado=EstadoServicio.PUBLICADO,
        )

        servicio_devuelto = servicio_service.convocar(
            db_session,
            servicio.id,
            voluntario_ids=[vol_con_dispositivo.id],
        )

        assert servicio_devuelto.estado == EstadoServicio.ACTIVO

        notifs = db_session.exec(select(Notificacion)).all()
        assert notifs == []


class TestConvocatoriaCaeNotificacion:
    def test_si_falla_la_notificacion_la_convocatoria_persiste(
        self,
        db_session,
        vol_con_dispositivo,
        make_servicio,
        ntfy,
    ):
        """Defensa: un fallo catastrófico del subsistema de
        notificaciones no debe revertir la activación del servicio.
        Forzamos un 5xx en FCM y comprobamos que el servicio quedó en
        ACTIVO pese al fallo de envío."""

        fcm_roto = FakeFcmAdmin(tokens_5xx={f"tok-{vol_con_dispositivo.id}"})
        servicio = make_servicio(
            tipo=TipoServicio.PREVENTIVO,
            estado=EstadoServicio.PUBLICADO,
        )

        servicio_devuelto = servicio_service.convocar(
            db_session,
            servicio.id,
            voluntario_ids=[vol_con_dispositivo.id],
            fcm_client=fcm_roto,
            ntfy_client=ntfy,
        )

        assert servicio_devuelto.estado == EstadoServicio.ACTIVO
