"""Tests del Service de fichajes (EN-04-02 + EN-04-03 + US-04-05)."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.models.inscripcion_servicio import TipoInscripcion
from app.repositories import servicios as servicios_repo
from app.services import fichajes as service
from app.services import servicios as servicios_service
from app.services.servicios import ServicioNoEncontrado


def _inscribir(db_session, servicio_id, voluntario_id, tipo=TipoInscripcion.INSCRITO):
    """Inscribe rápido en un servicio sin pasar por la API."""

    return servicios_repo.upsert_inscripcion(
        db_session,
        servicio_id=servicio_id,
        voluntario_id=voluntario_id,
        tipo=tipo,
        fecha=datetime(2026, 6, 1, 8, 0),
    )


# ---------------------------------------------------------------------------
# Fichar entrada (CU-05)
# ---------------------------------------------------------------------------


class TestFicharEntrada:
    def test_entrada_funciona_con_inscripcion_y_servicio_activo(
        self, db_session, servicio_activo, voluntario
    ):
        _inscribir(db_session, servicio_activo.id, voluntario.id)
        fichaje = service.fichar_entrada(
            db_session,
            servicio_id=servicio_activo.id,
            voluntario_id=voluntario.id,
        )
        assert fichaje.hora_entrada is not None
        assert fichaje.hora_salida is None
        assert fichaje.automatico is False

    def test_entrada_funciona_como_convocado(
        self, db_session, servicio_activo, voluntario
    ):
        _inscribir(
            db_session,
            servicio_activo.id,
            voluntario.id,
            tipo=TipoInscripcion.CONVOCADO,
        )
        fichaje = service.fichar_entrada(
            db_session,
            servicio_id=servicio_activo.id,
            voluntario_id=voluntario.id,
        )
        assert fichaje.id is not None

    def test_entrada_servicio_inexistente_lanza_404(
        self, db_session, voluntario
    ):
        with pytest.raises(ServicioNoEncontrado):
            service.fichar_entrada(
                db_session,
                servicio_id=uuid.uuid4(),
                voluntario_id=voluntario.id,
            )

    def test_entrada_servicio_borrador_falla(
        self, db_session, servicio_borrador, voluntario
    ):
        _inscribir(db_session, servicio_borrador.id, voluntario.id)
        with pytest.raises(service.ServicioNoActivo):
            service.fichar_entrada(
                db_session,
                servicio_id=servicio_borrador.id,
                voluntario_id=voluntario.id,
            )

    def test_entrada_servicio_publicado_falla(
        self, db_session, servicio_publicado, voluntario
    ):
        _inscribir(db_session, servicio_publicado.id, voluntario.id)
        with pytest.raises(service.ServicioNoActivo):
            service.fichar_entrada(
                db_session,
                servicio_id=servicio_publicado.id,
                voluntario_id=voluntario.id,
            )

    def test_entrada_voluntario_no_inscrito_falla(
        self, db_session, servicio_activo, voluntario
    ):
        with pytest.raises(service.VoluntarioNoInscritoNiConvocado):
            service.fichar_entrada(
                db_session,
                servicio_id=servicio_activo.id,
                voluntario_id=voluntario.id,
            )

    def test_entrada_doble_falla(
        self, db_session, servicio_activo, voluntario
    ):
        _inscribir(db_session, servicio_activo.id, voluntario.id)
        service.fichar_entrada(
            db_session,
            servicio_id=servicio_activo.id,
            voluntario_id=voluntario.id,
        )
        with pytest.raises(service.YaFichado):
            service.fichar_entrada(
                db_session,
                servicio_id=servicio_activo.id,
                voluntario_id=voluntario.id,
            )


# ---------------------------------------------------------------------------
# Fichar salida (CU-06)
# ---------------------------------------------------------------------------


class TestFicharSalida:
    def test_salida_sella_hora_y_calcula_duracion(
        self, db_session, servicio_activo, voluntario
    ):
        _inscribir(db_session, servicio_activo.id, voluntario.id)
        service.fichar_entrada(
            db_session,
            servicio_id=servicio_activo.id,
            voluntario_id=voluntario.id,
            cuando=datetime(2026, 6, 1, 9, 0),
        )
        salida = service.fichar_salida(
            db_session,
            servicio_id=servicio_activo.id,
            voluntario_id=voluntario.id,
            cuando=datetime(2026, 6, 1, 14, 30),
        )
        assert salida.hora_salida == datetime(2026, 6, 1, 14, 30)
        assert salida.duracion_segundos == 5 * 3600 + 30 * 60

    def test_salida_sin_entrada_previa_lanza_404(
        self, db_session, servicio_activo, voluntario
    ):
        with pytest.raises(service.SinFichajeAbierto):
            service.fichar_salida(
                db_session,
                servicio_id=servicio_activo.id,
                voluntario_id=voluntario.id,
            )

    def test_salida_doble_falla(
        self, db_session, servicio_activo, voluntario
    ):
        _inscribir(db_session, servicio_activo.id, voluntario.id)
        service.fichar_entrada(
            db_session,
            servicio_id=servicio_activo.id,
            voluntario_id=voluntario.id,
        )
        service.fichar_salida(
            db_session,
            servicio_id=servicio_activo.id,
            voluntario_id=voluntario.id,
        )
        with pytest.raises(service.SinFichajeAbierto):
            service.fichar_salida(
                db_session,
                servicio_id=servicio_activo.id,
                voluntario_id=voluntario.id,
            )


# ---------------------------------------------------------------------------
# Lecturas
# ---------------------------------------------------------------------------


class TestLecturas:
    def test_listar_por_servicio_404(self, db_session):
        with pytest.raises(ServicioNoEncontrado):
            service.listar_por_servicio(db_session, uuid.uuid4())

    def test_listar_por_servicio_devuelve_pares(
        self, db_session, servicio_activo, voluntario
    ):
        _inscribir(db_session, servicio_activo.id, voluntario.id)
        service.fichar_entrada(
            db_session,
            servicio_id=servicio_activo.id,
            voluntario_id=voluntario.id,
        )
        pares = service.listar_por_servicio(db_session, servicio_activo.id)
        assert len(pares) == 1
        v, f = pares[0]
        assert v.id == voluntario.id

    def test_horas_acumuladas_propio(
        self, db_session, voluntario, make_servicio
    ):
        # Un fichaje cerrado de 1h + uno abierto.
        from app.repositories import fichajes as fichajes_repo

        s1 = make_servicio()
        s2 = make_servicio()
        fichajes_repo.create(
            db_session,
            data=dict(
                servicio_id=s1.id,
                voluntario_id=voluntario.id,
                hora_entrada=datetime(2026, 6, 1, 9, 0),
                hora_salida=datetime(2026, 6, 1, 10, 0),
                automatico=False,
            ),
        )
        fichajes_repo.create(
            db_session,
            data=dict(
                servicio_id=s2.id,
                voluntario_id=voluntario.id,
                hora_entrada=datetime(2026, 6, 2, 9, 0),
                hora_salida=None,
                automatico=False,
            ),
        )
        total_seg, n_c, n_a = service.horas_acumuladas(db_session, voluntario.id)
        assert total_seg == 3600
        assert n_c == 1
        assert n_a == 1


# ---------------------------------------------------------------------------
# US-04-05: fichaje automático al cerrar servicio
# ---------------------------------------------------------------------------


class TestCierreAutomatico:
    def test_cerrar_servicio_cierra_fichajes_abiertos(
        self, db_session, servicio_activo, voluntario
    ):
        _inscribir(db_session, servicio_activo.id, voluntario.id)
        service.fichar_entrada(
            db_session,
            servicio_id=servicio_activo.id,
            voluntario_id=voluntario.id,
            cuando=datetime(2026, 6, 1, 9, 0),
        )
        # El voluntario olvida fichar salida. Cerramos el servicio.
        servicios_service.cerrar(
            db_session,
            servicio_activo.id,
            fecha_cierre=datetime(2026, 6, 1, 14, 0),
        )

        from app.repositories import fichajes as fichajes_repo

        f = fichajes_repo.get_por_servicio_y_voluntario(
            db_session,
            servicio_id=servicio_activo.id,
            voluntario_id=voluntario.id,
        )
        assert f is not None
        assert f.hora_salida == datetime(2026, 6, 1, 14, 0)
        assert f.automatico is True

    def test_cerrar_servicio_respeta_fichajes_ya_cerrados(
        self, db_session, servicio_activo, voluntario
    ):
        _inscribir(db_session, servicio_activo.id, voluntario.id)
        service.fichar_entrada(
            db_session,
            servicio_id=servicio_activo.id,
            voluntario_id=voluntario.id,
            cuando=datetime(2026, 6, 1, 9, 0),
        )
        service.fichar_salida(
            db_session,
            servicio_id=servicio_activo.id,
            voluntario_id=voluntario.id,
            cuando=datetime(2026, 6, 1, 13, 0),
        )
        # Ahora cerramos el servicio: el fichaje ya estaba sellado.
        servicios_service.cerrar(
            db_session,
            servicio_activo.id,
            fecha_cierre=datetime(2026, 6, 1, 14, 0),
        )

        from app.repositories import fichajes as fichajes_repo

        f = fichajes_repo.get_por_servicio_y_voluntario(
            db_session,
            servicio_id=servicio_activo.id,
            voluntario_id=voluntario.id,
        )
        assert f.hora_salida == datetime(2026, 6, 1, 13, 0)
        assert f.automatico is False

    def test_cerrar_servicio_sin_fichajes_no_falla(
        self, db_session, servicio_activo
    ):
        # Cerrar sin fichajes abiertos no debe romper.
        servicios_service.cerrar(db_session, servicio_activo.id)
