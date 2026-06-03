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
# Borrado físico de material y vehículo (corrección de errores de alta)
# ---------------------------------------------------------------------------


class TestEliminarMaterial:
    def test_eliminar_sin_asignaciones_borra(self, db_session, material):
        from app.repositories import inventario as repo

        service.eliminar_material(db_session, material.id)
        assert repo.get_material(db_session, material.id) is None

    def test_eliminar_con_asignacion_a_servicio_lanza_en_uso(
        self, db_session, servicio_publicado, make_material
    ):
        m = make_material(tipo=TipoMaterial.SERVICIO, cantidad=10)
        service.asignar_material_a_servicio(
            db_session,
            material_id=m.id,
            servicio_id=servicio_publicado.id,
            cantidad=2,
        )
        with pytest.raises(service.MaterialEnUso):
            service.eliminar_material(db_session, m.id)

    def test_eliminar_inexistente_lanza_404(self, db_session):
        with pytest.raises(service.MaterialNoEncontrado):
            service.eliminar_material(db_session, uuid.uuid4())


class TestEliminarVehiculo:
    def test_eliminar_sin_asignaciones_borra(self, db_session, vehiculo):
        from app.repositories import inventario as repo

        service.eliminar_vehiculo(db_session, vehiculo.id)
        assert repo.get_vehiculo(db_session, vehiculo.id) is None

    def test_eliminar_con_asignacion_a_servicio_lanza_en_uso(
        self, db_session, servicio_publicado, vehiculo
    ):
        service.asignar_vehiculo_a_servicio(
            db_session,
            vehiculo_id=vehiculo.id,
            servicio_id=servicio_publicado.id,
        )
        with pytest.raises(service.VehiculoEnUso):
            service.eliminar_vehiculo(db_session, vehiculo.id)

    def test_eliminar_con_dotacion_lanza_en_uso(
        self, db_session, make_material, make_vehiculo
    ):
        # La dotación fija referencia el vehículo por AsignacionMaterial.
        v = make_vehiculo()
        m = make_material(tipo=TipoMaterial.PRESTABLE, cantidad=2)
        service.asignar_dotacion_vehiculo(
            db_session, vehiculo_id=v.id, material_id=m.id
        )
        with pytest.raises(service.VehiculoEnUso):
            service.eliminar_vehiculo(db_session, v.id)

    def test_eliminar_inexistente_lanza_404(self, db_session):
        with pytest.raises(service.VehiculoNoEncontrado):
            service.eliminar_vehiculo(db_session, uuid.uuid4())


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

    def test_asignar_material_a_servicio_cerrado_falla(
        self, db_session, make_servicio, make_material
    ):
        from app.models.servicio import EstadoServicio

        cerrado = make_servicio(estado=EstadoServicio.CERRADO)
        m = make_material(tipo=TipoMaterial.SERVICIO, cantidad=10)
        with pytest.raises(service.ServicioCerrado):
            service.asignar_material_a_servicio(
                db_session,
                material_id=m.id,
                servicio_id=cerrado.id,
                cantidad=1,
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

    def test_vehiculo_solapado_falla(
        self,
        db_session,
        servicio_publicado,
        make_servicio,
        vehiculo,
    ):
        # Dos servicios publicados con el mismo intervalo por defecto
        # (09-14) solapan: el segundo bloquea (PR6 / Política A).
        from app.models.servicio import EstadoServicio

        otro = make_servicio(estado=EstadoServicio.PUBLICADO)
        service.asignar_vehiculo_a_servicio(
            db_session,
            vehiculo_id=vehiculo.id,
            servicio_id=servicio_publicado.id,
        )
        with pytest.raises(service.VehiculoOcupado):
            service.asignar_vehiculo_a_servicio(
                db_session,
                vehiculo_id=vehiculo.id,
                servicio_id=otro.id,
            )

    def test_asignar_vehiculo_a_servicio_cerrado_falla(
        self, db_session, make_servicio, vehiculo
    ):
        from app.models.servicio import EstadoServicio

        cerrado = make_servicio(estado=EstadoServicio.CERRADO)
        with pytest.raises(service.ServicioCerrado):
            service.asignar_vehiculo_a_servicio(
                db_session,
                vehiculo_id=vehiculo.id,
                servicio_id=cerrado.id,
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


# ---------------------------------------------------------------------------
# Dotación fija de material a vehículo (PR3 / SP-09)
# ---------------------------------------------------------------------------


class TestCheckConstraintTernario:
    """El CHECK ``ck_asignacion_material_target`` exige exactamente un target.

    Estos tests insertan filas crudas saltándose la lógica de servicio
    para validar la barrera de integridad de BD directamente. Requieren
    Postgres real (``::int`` no existe en SQLite).
    """

    def _insert(self, db_session, **targets):
        from sqlalchemy.exc import IntegrityError

        from app.models.asignacion_material import (
            AsignacionMaterial,
            TipoAsignacion,
        )

        asignacion = AsignacionMaterial(
            material_id=targets["material_id"],
            voluntario_id=targets.get("voluntario_id"),
            servicio_id=targets.get("servicio_id"),
            vehiculo_id=targets.get("vehiculo_id"),
            tipo=targets.get("tipo", TipoAsignacion.PERSONAL),
            cantidad=1,
            fecha_asignacion=datetime(2026, 6, 1, 9, 0),
        )
        db_session.add(asignacion)
        try:
            db_session.commit()
        except IntegrityError:
            db_session.rollback()
            raise
        return asignacion

    def test_cero_targets_rechazado(self, db_session, material):
        with pytest.raises(Exception) as exc:
            self._insert(db_session, material_id=material.id)
        assert "ck_asignacion_material_target" in str(exc.value)

    def test_dos_targets_rechazado(
        self, db_session, material, voluntario, servicio_borrador
    ):
        with pytest.raises(Exception) as exc:
            self._insert(
                db_session,
                material_id=material.id,
                voluntario_id=voluntario.id,
                servicio_id=servicio_borrador.id,
            )
        assert "ck_asignacion_material_target" in str(exc.value)

    def test_tres_targets_rechazado(
        self, db_session, voluntario, servicio_borrador, make_material, make_vehiculo
    ):
        from app.models.material import TipoMaterial

        material = make_material(tipo=TipoMaterial.PRESTABLE)
        vehiculo = make_vehiculo()
        with pytest.raises(Exception) as exc:
            self._insert(
                db_session,
                material_id=material.id,
                voluntario_id=voluntario.id,
                servicio_id=servicio_borrador.id,
                vehiculo_id=vehiculo.id,
            )
        assert "ck_asignacion_material_target" in str(exc.value)

    def test_un_target_voluntario_aceptado(self, db_session, material, voluntario):
        asignacion = self._insert(
            db_session, material_id=material.id, voluntario_id=voluntario.id
        )
        assert asignacion.id is not None

    def test_un_target_vehiculo_aceptado(self, db_session, make_material, make_vehiculo):
        from app.models.asignacion_material import TipoAsignacion
        from app.models.material import TipoMaterial

        material = make_material(tipo=TipoMaterial.PRESTABLE)
        vehiculo = make_vehiculo()
        asignacion = self._insert(
            db_session,
            material_id=material.id,
            vehiculo_id=vehiculo.id,
            tipo=TipoAsignacion.DOTACION_VEHICULO,
        )
        assert asignacion.id is not None
        assert asignacion.voluntario_id is None
        assert asignacion.servicio_id is None


class TestValidarCompatibilidadDotacion:
    """``_validar_compatibilidad_tipo`` con DOTACION_VEHICULO (PR3)."""

    def test_prestable_aceptado(self, make_material):
        from app.models.material import TipoMaterial

        material = make_material(tipo=TipoMaterial.PRESTABLE)
        # No lanza.
        service._validar_compatibilidad_tipo(
            material, TipoAsignacion.DOTACION_VEHICULO
        )

    def test_personal_rechazado(self, make_material):
        from app.models.material import TipoMaterial

        material = make_material(tipo=TipoMaterial.PERSONAL)
        with pytest.raises(service.TipoAsignacionNoCompatible):
            service._validar_compatibilidad_tipo(
                material, TipoAsignacion.DOTACION_VEHICULO
            )

    def test_servicio_rechazado(self, make_material):
        from app.models.material import TipoMaterial

        material = make_material(tipo=TipoMaterial.SERVICIO)
        with pytest.raises(service.TipoAsignacionNoCompatible):
            service._validar_compatibilidad_tipo(
                material, TipoAsignacion.DOTACION_VEHICULO
            )


class TestAsignarDotacionVehiculo:
    def test_asignar_correcto(self, db_session, make_material, make_vehiculo):
        from app.models.material import TipoMaterial

        material = make_material(tipo=TipoMaterial.PRESTABLE, cantidad=5)
        vehiculo = make_vehiculo()

        asignacion = service.asignar_dotacion_vehiculo(
            db_session,
            vehiculo_id=vehiculo.id,
            material_id=material.id,
            cantidad=2,
        )
        assert asignacion.tipo == TipoAsignacion.DOTACION_VEHICULO
        assert asignacion.vehiculo_id == vehiculo.id
        assert asignacion.voluntario_id is None
        assert asignacion.servicio_id is None
        assert asignacion.fecha_devolucion is None
        assert asignacion.cantidad == 2

    def test_asignar_material_personal_falla(
        self, db_session, make_material, make_vehiculo
    ):
        from app.models.material import TipoMaterial

        material = make_material(tipo=TipoMaterial.PERSONAL)
        vehiculo = make_vehiculo()
        with pytest.raises(service.TipoAsignacionNoCompatible):
            service.asignar_dotacion_vehiculo(
                db_session, vehiculo_id=vehiculo.id, material_id=material.id
            )

    def test_asignar_vehiculo_inexistente_404(self, db_session, make_material):
        from app.models.material import TipoMaterial

        material = make_material(tipo=TipoMaterial.PRESTABLE)
        with pytest.raises(service.VehiculoNoEncontrado):
            service.asignar_dotacion_vehiculo(
                db_session, vehiculo_id=uuid.uuid4(), material_id=material.id
            )

    def test_asignar_material_inexistente_404(self, db_session, make_vehiculo):
        vehiculo = make_vehiculo()
        with pytest.raises(service.MaterialNoEncontrado):
            service.asignar_dotacion_vehiculo(
                db_session, vehiculo_id=vehiculo.id, material_id=uuid.uuid4()
            )

    def test_asignar_material_averiado_falla(
        self, db_session, make_material, make_vehiculo
    ):
        from app.models.material import EstadoInventario, TipoMaterial

        material = make_material(
            tipo=TipoMaterial.PRESTABLE, estado=EstadoInventario.AVERIADO
        )
        vehiculo = make_vehiculo()
        with pytest.raises(service.MaterialNoOperativo):
            service.asignar_dotacion_vehiculo(
                db_session, vehiculo_id=vehiculo.id, material_id=material.id
            )

    def test_dotacion_cuenta_como_stock_consumido(
        self, db_session, voluntario, make_material, make_vehiculo
    ):
        # `Material.cantidad` es stock bruto e incluye lo dotado: una unidad
        # físicamente metida en un vehículo no puede prestarse a la vez. Con
        # cantidad=1 totalmente dotada, el préstamo a voluntario falla por
        # stock insuficiente.
        from app.models.material import TipoMaterial

        material = make_material(tipo=TipoMaterial.PRESTABLE, cantidad=1)
        vehiculo = make_vehiculo()

        service.asignar_dotacion_vehiculo(
            db_session, vehiculo_id=vehiculo.id, material_id=material.id
        )
        with pytest.raises(service.CantidadInsuficiente):
            service.asignar_material_a_voluntario(
                db_session,
                material_id=material.id,
                voluntario_id=voluntario.id,
                tipo=TipoAsignacion.PRESTAMO,
            )

    def test_dotacion_parcial_deja_stock_para_prestamo(
        self, db_session, voluntario, make_material, make_vehiculo
    ):
        # Con cantidad=2 y 1 dotada, queda 1 disponible para préstamo.
        from app.models.material import TipoMaterial

        material = make_material(tipo=TipoMaterial.PRESTABLE, cantidad=2)
        vehiculo = make_vehiculo()

        service.asignar_dotacion_vehiculo(
            db_session, vehiculo_id=vehiculo.id, material_id=material.id
        )
        prestamo = service.asignar_material_a_voluntario(
            db_session,
            material_id=material.id,
            voluntario_id=voluntario.id,
            tipo=TipoAsignacion.PRESTAMO,
        )
        assert prestamo.id is not None


class TestListarDotacionVehiculo:
    def test_lista_solo_dotacion_activa(
        self, db_session, make_material, make_vehiculo
    ):
        from app.models.material import TipoMaterial

        vehiculo = make_vehiculo()
        m1 = make_material(tipo=TipoMaterial.PRESTABLE, nombre="Botiquín")
        m2 = make_material(tipo=TipoMaterial.PRESTABLE, nombre="Extintor")
        service.asignar_dotacion_vehiculo(
            db_session, vehiculo_id=vehiculo.id, material_id=m1.id
        )
        d2 = service.asignar_dotacion_vehiculo(
            db_session, vehiculo_id=vehiculo.id, material_id=m2.id
        )
        # Liberar una: no debe aparecer.
        service.liberar_dotacion_vehiculo(
            db_session, vehiculo_id=vehiculo.id, asignacion_id=d2.id
        )

        dotacion = service.listar_dotacion_vehiculo(db_session, vehiculo.id)
        assert len(dotacion) == 1
        assert dotacion[0].material.nombre == "Botiquín"

    def test_listar_vehiculo_inexistente_404(self, db_session):
        with pytest.raises(service.VehiculoNoEncontrado):
            service.listar_dotacion_vehiculo(db_session, uuid.uuid4())


class TestLiberarDotacionVehiculo:
    def test_liberar_sella_fecha(self, db_session, make_material, make_vehiculo):
        from app.models.material import TipoMaterial

        vehiculo = make_vehiculo()
        material = make_material(tipo=TipoMaterial.PRESTABLE)
        dotacion = service.asignar_dotacion_vehiculo(
            db_session, vehiculo_id=vehiculo.id, material_id=material.id
        )
        cerrada = service.liberar_dotacion_vehiculo(
            db_session, vehiculo_id=vehiculo.id, asignacion_id=dotacion.id
        )
        assert cerrada.fecha_devolucion is not None
        assert cerrada.activa is False

    def test_liberar_inexistente_404(self, db_session, make_vehiculo):
        vehiculo = make_vehiculo()
        with pytest.raises(service.AsignacionNoEncontrada):
            service.liberar_dotacion_vehiculo(
                db_session, vehiculo_id=vehiculo.id, asignacion_id=uuid.uuid4()
            )

    def test_liberar_de_otro_vehiculo_404(
        self, db_session, make_material, make_vehiculo
    ):
        from app.models.material import TipoMaterial

        vehiculo_a = make_vehiculo()
        vehiculo_b = make_vehiculo()
        material = make_material(tipo=TipoMaterial.PRESTABLE)
        dotacion = service.asignar_dotacion_vehiculo(
            db_session, vehiculo_id=vehiculo_a.id, material_id=material.id
        )
        with pytest.raises(service.AsignacionNoEncontrada):
            service.liberar_dotacion_vehiculo(
                db_session, vehiculo_id=vehiculo_b.id, asignacion_id=dotacion.id
            )


class TestDotacionSobreviveCierreServicio:
    """Blindaje: la dotación fija (sin servicio_id) NO se libera al cerrar
    un servicio (PR3 / SP-09)."""

    def test_dotacion_persiste_tras_liberar_asignaciones_de_servicio(
        self, db_session, servicio_activo, make_material, make_vehiculo
    ):
        from app.models.material import TipoMaterial

        vehiculo = make_vehiculo()
        material = make_material(tipo=TipoMaterial.PRESTABLE)
        dotacion = service.asignar_dotacion_vehiculo(
            db_session, vehiculo_id=vehiculo.id, material_id=material.id
        )

        # Cerrar el servicio (ejecuta liberar_asignaciones_de_servicio).
        service.liberar_asignaciones_de_servicio(
            db_session,
            servicio_id=servicio_activo.id,
            cuando=datetime(2026, 6, 5, 18, 0),
        )

        viva = service.listar_dotacion_vehiculo(db_session, vehiculo.id)
        assert len(viva) == 1
        assert viva[0].id == dotacion.id
        assert viva[0].fecha_devolucion is None
