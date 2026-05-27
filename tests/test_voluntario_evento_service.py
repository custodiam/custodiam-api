"""Tests de `app.services.voluntario_evento` (EN-02-04 / US-02-06)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.models.fichaje import Fichaje
from app.models.inscripcion_servicio import InscripcionServicio, TipoInscripcion
from app.models.servicio import EstadoServicio
from app.models.voluntario_evento import TipoEventoVoluntario
from app.repositories import voluntario_evento as repo
from app.services import voluntario_evento as service
from app.services.voluntarios import VoluntarioNoEncontrado


@pytest.fixture
def yo(make_voluntario):
    return make_voluntario(keycloak_id="kc-yo")


class TestObtenerHistorialPropio:
    def test_devuelve_solo_mis_eventos(self, db_session, yo, make_voluntario):
        otro = make_voluntario(
            keycloak_id="kc-otro",
            nombre="Otro",
            telefono="+34699999999",
            dni="99999999X",
        )
        repo.registrar(
            db_session,
            voluntario_id=yo.id,
            tipo=TipoEventoVoluntario.ALTA,
        )
        repo.registrar(
            db_session,
            voluntario_id=otro.id,
            tipo=TipoEventoVoluntario.ALTA,
        )

        items, total = service.obtener_historial_propio(
            db_session, keycloak_id="kc-yo"
        )
        assert total == 1
        assert items[0].voluntario_id == yo.id

    def test_aplica_filtros(self, db_session, yo):
        repo.registrar(
            db_session,
            voluntario_id=yo.id,
            tipo=TipoEventoVoluntario.ALTA,
        )
        repo.registrar(
            db_session,
            voluntario_id=yo.id,
            tipo=TipoEventoVoluntario.FICHAJE_ENTRADA,
        )

        items, total = service.obtener_historial_propio(
            db_session,
            keycloak_id="kc-yo",
            tipos=[TipoEventoVoluntario.FICHAJE_ENTRADA],
        )
        assert total == 1
        assert items[0].tipo_evento == TipoEventoVoluntario.FICHAJE_ENTRADA

    def test_keycloak_sin_voluntario_lanza_404(self, db_session):
        with pytest.raises(VoluntarioNoEncontrado):
            service.obtener_historial_propio(
                db_session, keycloak_id="kc-no-existe"
            )


class TestObtenerResumenPropio:
    def test_resumen_sin_actividad_es_cero(self, db_session, yo):
        resumen = service.obtener_resumen_propio(
            db_session, keycloak_id="kc-yo"
        )
        assert resumen.horas_totales == 0
        assert resumen.segundos_totales == 0
        assert resumen.servicios_realizados == 0
        assert resumen.ultimo_servicio is None

    def test_resumen_calcula_horas_desde_fichajes_cerrados(
        self, db_session, yo, make_servicio
    ):
        servicio = make_servicio(estado=EstadoServicio.CERRADO)
        entrada = datetime(2026, 4, 1, 9, 0)
        salida = entrada + timedelta(hours=3)
        db_session.add(
            Fichaje(
                servicio_id=servicio.id,
                voluntario_id=yo.id,
                hora_entrada=entrada,
                hora_salida=salida,
                automatico=False,
            )
        )
        db_session.add(
            InscripcionServicio(
                servicio_id=servicio.id,
                voluntario_id=yo.id,
                tipo=TipoInscripcion.INSCRITO,
                fecha=entrada,
            )
        )
        db_session.commit()

        resumen = service.obtener_resumen_propio(
            db_session, keycloak_id="kc-yo"
        )
        assert resumen.segundos_totales == 3 * 3600
        assert resumen.horas_totales == 3
        assert resumen.servicios_realizados == 1
        assert resumen.ultimo_servicio is not None
        assert resumen.ultimo_servicio.servicio_id == servicio.id

    def test_resumen_ignora_servicios_no_cerrados(
        self, db_session, yo, make_servicio
    ):
        activo = make_servicio(estado=EstadoServicio.ACTIVO)
        db_session.add(
            InscripcionServicio(
                servicio_id=activo.id,
                voluntario_id=yo.id,
                tipo=TipoInscripcion.INSCRITO,
                fecha=datetime.now(),
            )
        )
        db_session.commit()

        resumen = service.obtener_resumen_propio(
            db_session, keycloak_id="kc-yo"
        )
        assert resumen.servicios_realizados == 0
        assert resumen.ultimo_servicio is None
