"""Tests del Service de inventario (EN-05-02 + EN-05-03 + EN-05-04)."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.models.asignacion_material import TipoAsignacion
from app.models.material import EstadoInventario, TipoMaterial
from app.schemas.inventario import (
    MaterialCreate,
    MaterialUpdate,
    VehiculoCreate,
)
from app.services import inventario as service
from app.services import servicios as servicios_service

# ---------------------------------------------------------------------------
# Alta de material y vehículo
# ---------------------------------------------------------------------------


class TestCrearMaterial:
    def _payload(self, **overrides):
        base = dict(
            nombre="Casco",
            tipo=TipoMaterial.PERSONAL,
            cantidad=1,
            ubicacion_base="Base",
        )
        base.update(overrides)
        return MaterialCreate(**base)

    def test_crear_genera_codigo_si_no_se_da(self, db_session):
        m = service.crear_material(db_session, self._payload())
        assert m.codigo is not None
        assert m.codigo.startswith("MAT-")
        assert m.estado == EstadoInventario.OPERATIVO

    def test_crear_respeta_codigo_explicito(self, db_session):
        m = service.crear_material(db_session, self._payload(codigo="CUSTOM-001"))
        assert m.codigo == "CUSTOM-001"

    def test_actualizar_aplica_campos(self, db_session, material):
        actualizado = service.actualizar_material(
            db_session, material.id, MaterialUpdate(ubicacion_base="Garaje 2")
        )
        assert actualizado.ubicacion_base == "Garaje 2"

    def test_actualizar_inexistente_lanza_404(self, db_session):
        with pytest.raises(service.MaterialNoEncontrado):
            service.actualizar_material(
                db_session, uuid.uuid4(), MaterialUpdate(nombre="x")
            )


class TestCrearVehiculo:
    def test_crear_arranca_en_operativo(self, db_session):
        v = service.crear_vehiculo(
            db_session,
            VehiculoCreate(
                codigo_interno="VH-001",
                matricula="1234-AAA",
                tipo="furgoneta",
                ubicacion_base="Base",
            ),
        )
        assert v.estado == EstadoInventario.OPERATIVO


# ---------------------------------------------------------------------------
# Incidencias (CU-24)
# ---------------------------------------------------------------------------


class TestIncidenciaMaterial:
    def test_reportar_averia_cambia_estado(self, db_session, material):
        m = service.reportar_incidencia_material(
            db_session,
            material.id,
            nuevo_estado=EstadoInventario.AVERIADO,
            descripcion="Correa rota",
        )
        assert m.estado == EstadoInventario.AVERIADO
        assert m.observaciones_incidencia == "Correa rota"

    def test_reportar_perdida_cambia_estado(self, db_session, material):
        m = service.reportar_incidencia_material(
            db_session,
            material.id,
            nuevo_estado=EstadoInventario.PERDIDO,
            descripcion="Se cayó en el río",
        )
        assert m.estado == EstadoInventario.PERDIDO

    def test_estado_invalido_lanza(self, db_session, material):
        with pytest.raises(service.EstadoIncidenciaInvalido):
            service.reportar_incidencia_material(
                db_session,
                material.id,
                nuevo_estado=EstadoInventario.OPERATIVO,
                descripcion="x",
            )

    def test_material_perdido_es_estado_final(
        self, db_session, make_material
    ):
        m = make_material(estado=EstadoInventario.PERDIDO)
        with pytest.raises(service.MaterialEnEstadoFinal):
            service.reportar_incidencia_material(
                db_session,
                m.id,
                nuevo_estado=EstadoInventario.AVERIADO,
                descripcion="x",
            )

    def test_reparar_vuelve_a_operativo(self, db_session, make_material):
        m = make_material(estado=EstadoInventario.AVERIADO)
        reparado = service.reparar_material(db_session, m.id)
        assert reparado.estado == EstadoInventario.OPERATIVO

    def test_reparar_perdido_falla(self, db_session, make_material):
        m = make_material(estado=EstadoInventario.PERDIDO)
        with pytest.raises(service.MaterialEnEstadoFinal):
            service.reparar_material(db_session, m.id)


class TestIncidenciaVehiculo:
    def test_reportar_averia_cambia_estado(self, db_session, vehiculo):
        v = service.reportar_incidencia_vehiculo(
            db_session,
            vehiculo.id,
            nuevo_estado=EstadoInventario.AVERIADO,
            descripcion="Embrague",
        )
        assert v.estado == EstadoInventario.AVERIADO


# ---------------------------------------------------------------------------
# Asignar material a voluntario (CU-21 / US-05-03 + US-05-04)
# ---------------------------------------------------------------------------


class TestAsignarMaterialAVoluntario:
    def test_asignar_personal_correcto(self, db_session, voluntario, make_material):
        m = make_material(tipo=TipoMaterial.PERSONAL, cantidad=1)
        a = service.asignar_material_a_voluntario(
            db_session,
            material_id=m.id,
            voluntario_id=voluntario.id,
            tipo=TipoAsignacion.PERSONAL,
        )
        assert a.activa is True
        # Stock totalmente consumido → EN_USO.
        from app.repositories import inventario as repo

        recuperado = repo.get_material(db_session, m.id)
        assert recuperado.estado == EstadoInventario.EN_USO

    def test_asignar_prestamo_correcto(self, db_session, voluntario, make_material):
        m = make_material(tipo=TipoMaterial.PRESTABLE, cantidad=5)
        a = service.asignar_material_a_voluntario(
            db_session,
            material_id=m.id,
            voluntario_id=voluntario.id,
            tipo=TipoAsignacion.PRESTAMO,
            cantidad=2,
        )
        assert a.cantidad == 2

    def test_asignar_personal_a_material_servicio_falla(
        self, db_session, voluntario, make_material
    ):
        m = make_material(tipo=TipoMaterial.SERVICIO, cantidad=1)
        with pytest.raises(service.TipoAsignacionNoCompatible):
            service.asignar_material_a_voluntario(
                db_session,
                material_id=m.id,
                voluntario_id=voluntario.id,
                tipo=TipoAsignacion.PERSONAL,
            )

    def test_asignar_personal_requiere_tipo_personal(
        self, db_session, voluntario, make_material
    ):
        m = make_material(tipo=TipoMaterial.PRESTABLE, cantidad=1)
        with pytest.raises(service.TipoAsignacionNoCompatible):
            service.asignar_material_a_voluntario(
                db_session,
                material_id=m.id,
                voluntario_id=voluntario.id,
                tipo=TipoAsignacion.PERSONAL,
            )

    def test_asignar_prestamo_requiere_tipo_prestable(
        self, db_session, voluntario, make_material
    ):
        m = make_material(tipo=TipoMaterial.PERSONAL, cantidad=1)
        with pytest.raises(service.TipoAsignacionNoCompatible):
            service.asignar_material_a_voluntario(
                db_session,
                material_id=m.id,
                voluntario_id=voluntario.id,
                tipo=TipoAsignacion.PRESTAMO,
            )

    def test_asignar_dobla_lanza_ya_asignado(
        self, db_session, voluntario, make_material
    ):
        m = make_material(tipo=TipoMaterial.PRESTABLE, cantidad=5)
        service.asignar_material_a_voluntario(
            db_session,
            material_id=m.id,
            voluntario_id=voluntario.id,
            tipo=TipoAsignacion.PRESTAMO,
        )
        with pytest.raises(service.MaterialYaAsignadoAVoluntario):
            service.asignar_material_a_voluntario(
                db_session,
                material_id=m.id,
                voluntario_id=voluntario.id,
                tipo=TipoAsignacion.PRESTAMO,
            )

    def test_asignar_sin_stock_falla(
        self, db_session, voluntario, make_voluntario, make_material
    ):
        m = make_material(tipo=TipoMaterial.PRESTABLE, cantidad=1)
        otro = make_voluntario(nombre="Otra")
        service.asignar_material_a_voluntario(
            db_session,
            material_id=m.id,
            voluntario_id=voluntario.id,
            tipo=TipoAsignacion.PRESTAMO,
        )
        with pytest.raises(service.CantidadInsuficiente):
            service.asignar_material_a_voluntario(
                db_session,
                material_id=m.id,
                voluntario_id=otro.id,
                tipo=TipoAsignacion.PRESTAMO,
            )

    def test_asignar_material_averiado_falla(
        self, db_session, voluntario, make_material
    ):
        m = make_material(
            tipo=TipoMaterial.PERSONAL,
            estado=EstadoInventario.AVERIADO,
        )
        with pytest.raises(service.MaterialNoOperativo):
            service.asignar_material_a_voluntario(
                db_session,
                material_id=m.id,
                voluntario_id=voluntario.id,
                tipo=TipoAsignacion.PERSONAL,
            )


# ---------------------------------------------------------------------------
# Devolución (CU-23 / US-05-05)
# ---------------------------------------------------------------------------


class TestDevolver:
    def test_devolver_libera_estado(self, db_session, voluntario, make_material):
        m = make_material(tipo=TipoMaterial.PERSONAL, cantidad=1)
        service.asignar_material_a_voluntario(
            db_session,
            material_id=m.id,
            voluntario_id=voluntario.id,
            tipo=TipoAsignacion.PERSONAL,
        )
        service.devolver_material(
            db_session,
            material_id=m.id,
            voluntario_id=voluntario.id,
            observaciones="Sin daños",
        )
        from app.repositories import inventario as repo

        recuperado = repo.get_material(db_session, m.id)
        assert recuperado.estado == EstadoInventario.OPERATIVO

    def test_devolver_sin_asignacion_lanza(
        self, db_session, voluntario, make_material
    ):
        m = make_material()
        with pytest.raises(service.AsignacionNoEncontrada):
            service.devolver_material(
                db_session, material_id=m.id, voluntario_id=voluntario.id
            )


# ---------------------------------------------------------------------------
# Asignar material a servicio (CU-22 / US-05-06)
# ---------------------------------------------------------------------------


class TestAsignarMaterialAServicio:
    def test_asignar_correcto(
        self, db_session, servicio_publicado, make_material
    ):
        m = make_material(tipo=TipoMaterial.SERVICIO, cantidad=10)
        a = service.asignar_material_a_servicio(
            db_session,
            material_id=m.id,
            servicio_id=servicio_publicado.id,
            cantidad=3,
        )
        assert a.cantidad == 3
        assert a.voluntario_id is None

    def test_asignar_material_personal_a_servicio_falla(
        self, db_session, servicio_publicado, make_material
    ):
        m = make_material(tipo=TipoMaterial.PERSONAL, cantidad=1)
        with pytest.raises(service.TipoAsignacionNoCompatible):
            service.asignar_material_a_servicio(
                db_session,
                material_id=m.id,
                servicio_id=servicio_publicado.id,
            )

    def test_asignar_sin_stock_para_servicio_falla(
        self, db_session, servicio_publicado, voluntario, make_material
    ):
        # Material SERVICIO, pero PRESTABLE no aplica aquí. Comprobamos:
        # material SERVICIO con cantidad=2, 0 asignaciones a voluntario,
        # pedimos 3 → fail.
        m = make_material(tipo=TipoMaterial.SERVICIO, cantidad=2)
        with pytest.raises(service.CantidadInsuficiente):
            service.asignar_material_a_servicio(
                db_session,
                material_id=m.id,
                servicio_id=servicio_publicado.id,
                cantidad=3,
            )


# ---------------------------------------------------------------------------
# Asignar vehículo a servicio (CU-22 / US-05-07)
# ---------------------------------------------------------------------------


class TestAsignarVehiculoAServicio:
    def test_asignar_correcto_pone_en_uso(
        self, db_session, servicio_publicado, vehiculo
    ):
        a = service.asignar_vehiculo_a_servicio(
            db_session,
            vehiculo_id=vehiculo.id,
            servicio_id=servicio_publicado.id,
        )
        assert a.activa is True
        from app.repositories import inventario as repo

        recuperado = repo.get_vehiculo(db_session, vehiculo.id)
        assert recuperado.estado == EstadoInventario.EN_USO

    def test_vehiculo_no_operativo_falla(
        self, db_session, servicio_publicado, make_vehiculo
    ):
        v = make_vehiculo(estado=EstadoInventario.AVERIADO)
        with pytest.raises(service.VehiculoNoOperativo):
            service.asignar_vehiculo_a_servicio(
                db_session,
                vehiculo_id=v.id,
                servicio_id=servicio_publicado.id,
            )

    def test_vehiculo_ya_asignado_falla(
        self,
        db_session,
        servicio_publicado,
        make_servicio,
        vehiculo,
    ):
        from app.models.servicio import EstadoServicio

        otro = make_servicio(estado=EstadoServicio.PUBLICADO)
        service.asignar_vehiculo_a_servicio(
            db_session,
            vehiculo_id=vehiculo.id,
            servicio_id=servicio_publicado.id,
        )
        with pytest.raises(service.VehiculoYaAsignado):
            service.asignar_vehiculo_a_servicio(
                db_session,
                vehiculo_id=vehiculo.id,
                servicio_id=otro.id,
            )


# ---------------------------------------------------------------------------
# Liberación automática al cerrar servicio (E03 → E05)
# ---------------------------------------------------------------------------


class TestCierreLiberaAsignaciones:
    def test_cerrar_servicio_libera_material_y_vehiculo(
        self, db_session, make_material, servicio_activo, vehiculo
    ):
        mat = make_material(tipo=TipoMaterial.SERVICIO, cantidad=5)
        service.asignar_material_a_servicio(
            db_session,
            material_id=mat.id,
            servicio_id=servicio_activo.id,
            cantidad=2,
        )
        service.asignar_vehiculo_a_servicio(
            db_session,
            vehiculo_id=vehiculo.id,
            servicio_id=servicio_activo.id,
        )

        servicios_service.cerrar(
            db_session,
            servicio_activo.id,
            fecha_cierre=datetime(2026, 6, 5, 18, 0),
        )

        # Asignaciones cerradas
        from app.repositories import inventario as repo

        assert repo.list_asignaciones_activas_servicio_material(
            db_session, servicio_activo.id
        ) == []
        assert repo.list_asignaciones_activas_servicio_vehiculo(
            db_session, servicio_activo.id
        ) == []

        # Vehículo vuelve a OPERATIVO
        recuperado = repo.get_vehiculo(db_session, vehiculo.id)
        assert recuperado.estado == EstadoInventario.OPERATIVO

    def test_cerrar_servicio_sin_recursos_no_falla(
        self, db_session, servicio_activo
    ):
        # No hay nada asignado al servicio. Cerrar no debe romper.
        servicios_service.cerrar(db_session, servicio_activo.id)
