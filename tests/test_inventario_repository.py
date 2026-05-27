"""Tests del Repository de inventario (EN-05-02)."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.models.asignacion_material import AsignacionMaterial, TipoAsignacion
from app.models.material import EstadoInventario, TipoMaterial
from app.models.vehiculo import TipoVehiculo
from app.repositories import inventario as repo

# ---------------------------------------------------------------------------
# Material
# ---------------------------------------------------------------------------


class TestMaterialBasico:
    def test_get_devuelve_none_si_no_existe(self, db_session):
        assert repo.get_material(db_session, uuid.uuid4()) is None

    def test_create_persiste_material(self, db_session):
        m = repo.create_material(
            db_session,
            data=dict(
                nombre="Cono",
                tipo=TipoMaterial.SERVICIO,
                estado=EstadoInventario.OPERATIVO,
                cantidad=10,
                ubicacion_base="Base",
                codigo="CONO-001",
            ),
        )
        assert m.id is not None
        assert m.estado == EstadoInventario.OPERATIVO

    def test_update_aplica_campos(self, db_session, material):
        actualizado = repo.update_material(
            db_session, material, data={"ubicacion_base": "Garaje secundario"}
        )
        assert actualizado.ubicacion_base == "Garaje secundario"

    def test_set_estado_cambia_y_aplica_observacion(self, db_session, material):
        actualizado = repo.set_estado_material(
            db_session,
            material,
            nuevo_estado=EstadoInventario.AVERIADO,
            observaciones_incidencia="Correa rota",
        )
        assert actualizado.estado == EstadoInventario.AVERIADO
        assert actualizado.observaciones_incidencia == "Correa rota"

    def test_get_por_codigo_localiza(self, db_session, make_material):
        make_material(codigo="UNICO-001")
        assert (
            repo.get_material_por_codigo(db_session, "UNICO-001") is not None
        )
        assert repo.get_material_por_codigo(db_session, "NO-EXISTE") is None


class TestListMateriales:
    @pytest.fixture
    def trio(self, make_material):
        return [
            make_material(
                nombre="Casco amarillo",
                tipo=TipoMaterial.PERSONAL,
                categoria="EPI",
            ),
            make_material(
                nombre="Botiquín DESA",
                tipo=TipoMaterial.PRESTABLE,
                categoria="Sanitario",
            ),
            make_material(
                nombre="Cono naranja",
                tipo=TipoMaterial.SERVICIO,
                categoria="Señalización",
                estado=EstadoInventario.AVERIADO,
                cantidad=5,
            ),
        ]

    def test_lista_vacia(self, db_session):
        items, total = repo.list_materiales(db_session)
        assert items == []
        assert total == 0

    def test_devuelve_total_y_items(self, db_session, trio):
        items, total = repo.list_materiales(db_session)
        assert total == 3
        assert len(items) == 3

    def test_filtro_tipo(self, db_session, trio):
        items, total = repo.list_materiales(
            db_session, tipo=TipoMaterial.PRESTABLE
        )
        assert total == 1
        assert items[0].nombre == "Botiquín DESA"

    def test_filtro_estado(self, db_session, trio):
        items, total = repo.list_materiales(
            db_session, estado=EstadoInventario.AVERIADO
        )
        assert total == 1
        assert items[0].nombre == "Cono naranja"

    def test_filtro_categoria(self, db_session, trio):
        items, total = repo.list_materiales(
            db_session, categoria="Sanitario"
        )
        assert total == 1

    def test_filtro_q_por_nombre(self, db_session, trio):
        items, total = repo.list_materiales(db_session, q="casco")
        assert total == 1
        assert items[0].nombre == "Casco amarillo"

    def test_filtro_q_por_codigo(self, db_session, make_material):
        make_material(codigo="ABC-999")
        items, total = repo.list_materiales(db_session, q="abc-999")
        assert total == 1


# ---------------------------------------------------------------------------
# Vehiculo
# ---------------------------------------------------------------------------


class TestVehiculoBasico:
    def test_create_persiste_vehiculo(self, db_session):
        v = repo.create_vehiculo(
            db_session,
            data=dict(
                codigo_interno="VH-001",
                matricula="9999-AAA",
                tipo=TipoVehiculo.AMBULANCIA,
                estado=EstadoInventario.OPERATIVO,
                ubicacion_base="Base",
            ),
        )
        assert v.id is not None

    def test_update_aplica_campos(self, db_session, vehiculo):
        actualizado = repo.update_vehiculo(
            db_session, vehiculo, data={"marca_modelo": "Renault Master"}
        )
        assert actualizado.marca_modelo == "Renault Master"

    def test_set_estado_cambia(self, db_session, vehiculo):
        repo.set_estado_vehiculo(
            db_session, vehiculo, nuevo_estado=EstadoInventario.AVERIADO
        )
        recuperado = repo.get_vehiculo(db_session, vehiculo.id)
        assert recuperado.estado == EstadoInventario.AVERIADO

    def test_get_por_codigo_localiza(self, db_session, make_vehiculo):
        make_vehiculo(codigo_interno="UNICO-V-001")
        assert (
            repo.get_vehiculo_por_codigo(db_session, "UNICO-V-001") is not None
        )

    def test_list_filtros(self, db_session, make_vehiculo):
        make_vehiculo(codigo_interno="VH-A", tipo=TipoVehiculo.AMBULANCIA)
        make_vehiculo(codigo_interno="VH-F", tipo=TipoVehiculo.FURGONETA)
        items, total = repo.list_vehiculos(
            db_session, tipo=TipoVehiculo.AMBULANCIA
        )
        assert total == 1


# ---------------------------------------------------------------------------
# AsignacionMaterial
# ---------------------------------------------------------------------------


class TestAsignacionMaterial:
    def test_create_persiste(self, db_session, material, voluntario):
        a = repo.create_asignacion_material(
            db_session,
            data=dict(
                material_id=material.id,
                voluntario_id=voluntario.id,
                tipo=TipoAsignacion.PERSONAL,
                cantidad=1,
                fecha_asignacion=datetime(2026, 6, 1, 9, 0),
            ),
        )
        assert a.id is not None
        assert a.activa is True
        assert a.servicio_id is None

    def test_get_asignacion_activa_localiza(
        self, db_session, material, voluntario
    ):
        repo.create_asignacion_material(
            db_session,
            data=dict(
                material_id=material.id,
                voluntario_id=voluntario.id,
                tipo=TipoAsignacion.PERSONAL,
                cantidad=1,
                fecha_asignacion=datetime(2026, 6, 1, 9, 0),
            ),
        )
        encontrada = repo.get_asignacion_activa_material_voluntario(
            db_session,
            material_id=material.id,
            voluntario_id=voluntario.id,
        )
        assert encontrada is not None

    def test_cerrar_asignacion_sella_fecha(
        self, db_session, material, voluntario
    ):
        a = repo.create_asignacion_material(
            db_session,
            data=dict(
                material_id=material.id,
                voluntario_id=voluntario.id,
                tipo=TipoAsignacion.PERSONAL,
                cantidad=1,
                fecha_asignacion=datetime(2026, 6, 1, 9, 0),
            ),
        )
        repo.cerrar_asignacion_material(
            db_session,
            a,
            cuando=datetime(2026, 6, 5, 18, 0),
            observaciones_devolucion="Sin daños",
        )
        recuperada = repo.get_asignacion_material(db_session, a.id)
        assert recuperada.fecha_devolucion == datetime(2026, 6, 5, 18, 0)
        assert recuperada.observaciones_devolucion == "Sin daños"
        assert recuperada.activa is False

    def test_count_unidades_asignadas(
        self, db_session, make_material, voluntario, make_voluntario
    ):
        mat = make_material(cantidad=5, tipo=TipoMaterial.PRESTABLE)
        otro = make_voluntario(nombre="Otro")
        # 2 unidades activas a 2 voluntarios.
        repo.create_asignacion_material(
            db_session,
            data=dict(
                material_id=mat.id,
                voluntario_id=voluntario.id,
                tipo=TipoAsignacion.PRESTAMO,
                cantidad=2,
                fecha_asignacion=datetime(2026, 6, 1, 9, 0),
            ),
        )
        repo.create_asignacion_material(
            db_session,
            data=dict(
                material_id=mat.id,
                voluntario_id=otro.id,
                tipo=TipoAsignacion.PRESTAMO,
                cantidad=1,
                fecha_asignacion=datetime(2026, 6, 1, 10, 0),
            ),
        )
        assert repo.count_unidades_asignadas_material(db_session, mat.id) == 3

    def test_check_constraint_xor_target(self, db_session, material):
        """ck_asignacion_material_target: ambos nulls debe fallar."""

        db_session.add(
            AsignacionMaterial(
                material_id=material.id,
                voluntario_id=None,
                servicio_id=None,
                tipo=TipoAsignacion.SERVICIO,
                cantidad=1,
                fecha_asignacion=datetime(2026, 6, 1, 9, 0),
            )
        )
        with pytest.raises(Exception):
            db_session.commit()
        db_session.rollback()


# ---------------------------------------------------------------------------
# AsignacionVehiculo
# ---------------------------------------------------------------------------


class TestAsignacionVehiculo:
    def test_create_y_cerrar(self, db_session, vehiculo, servicio_publicado):
        a = repo.create_asignacion_vehiculo(
            db_session,
            data=dict(
                vehiculo_id=vehiculo.id,
                servicio_id=servicio_publicado.id,
                fecha_asignacion=datetime(2026, 6, 1, 9, 0),
            ),
        )
        assert a.id is not None
        assert a.activa is True

        repo.cerrar_asignacion_vehiculo(
            db_session, a, cuando=datetime(2026, 6, 5, 18, 0)
        )
        recuperada = repo.get_asignacion_vehiculo(db_session, a.id)
        assert recuperada.fecha_devolucion == datetime(2026, 6, 5, 18, 0)
        assert recuperada.activa is False

    def test_get_activa_localiza_sola(
        self, db_session, vehiculo, servicio_publicado
    ):
        a = repo.create_asignacion_vehiculo(
            db_session,
            data=dict(
                vehiculo_id=vehiculo.id,
                servicio_id=servicio_publicado.id,
                fecha_asignacion=datetime(2026, 6, 1, 9, 0),
            ),
        )
        assert (
            repo.get_asignacion_activa_vehiculo(db_session, vehiculo.id).id
            == a.id
        )

    def test_lista_por_servicio(
        self, db_session, make_vehiculo, servicio_publicado
    ):
        v1 = make_vehiculo(codigo_interno="V-01")
        v2 = make_vehiculo(codigo_interno="V-02")
        repo.create_asignacion_vehiculo(
            db_session,
            data=dict(
                vehiculo_id=v1.id,
                servicio_id=servicio_publicado.id,
                fecha_asignacion=datetime(2026, 6, 1, 9, 0),
            ),
        )
        repo.create_asignacion_vehiculo(
            db_session,
            data=dict(
                vehiculo_id=v2.id,
                servicio_id=servicio_publicado.id,
                fecha_asignacion=datetime(2026, 6, 1, 9, 5),
            ),
        )
        activas = repo.list_asignaciones_activas_servicio_vehiculo(
            db_session, servicio_publicado.id
        )
        assert len(activas) == 2
