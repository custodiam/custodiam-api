"""Tests de trazabilidad del estado actual de material y vehículo (PR1).

Cubre que la response de DETALLE expone "dónde está / a quién está
asignado" un activo, mientras que el listado (Summary) NO lo hace y no
dispara N+1.

- Material (stock, varias activas a la vez): ``asignaciones_activas`` +
  ``unidades_asignadas``.
- Vehículo (unidad única): ``asignacion_actual`` singular o ``None``.
"""

from __future__ import annotations

import uuid

from app.models.material import TipoMaterial
from app.services import inventario as service

BASE = "/api/v1/inventario"


# ---------------------------------------------------------------------------
# Material — asignaciones_activas + unidades_asignadas (detalle)
# ---------------------------------------------------------------------------


class TestMaterialTrazabilidadDetalle:
    def test_material_sin_asignaciones_lista_vacia(self, jefe_client, material):
        r = jefe_client.get(f"{BASE}/material/{material.id}")
        assert r.status_code == 200
        body = r.json()
        assert body["asignaciones_activas"] == []
        assert body["unidades_asignadas"] == 0

    def test_material_con_prestamos_y_dotacion(
        self,
        jefe_client,
        db_session,
        make_material,
        make_voluntario,
        make_vehiculo,
    ):
        # Material PRESTABLE con stock 10: 2 préstamos a voluntarios +
        # 1 dotación a un vehículo.
        mat = make_material(tipo=TipoMaterial.PRESTABLE, cantidad=10)
        vol_a = make_voluntario(nombre="Vol A")
        vol_b = make_voluntario(nombre="Vol B")
        veh = make_vehiculo()

        from app.models.asignacion_material import TipoAsignacion

        service.asignar_material_a_voluntario(
            db_session,
            material_id=mat.id,
            voluntario_id=vol_a.id,
            tipo=TipoAsignacion.PRESTAMO,
            cantidad=2,
        )
        service.asignar_material_a_voluntario(
            db_session,
            material_id=mat.id,
            voluntario_id=vol_b.id,
            tipo=TipoAsignacion.PRESTAMO,
            cantidad=3,
        )
        service.asignar_dotacion_vehiculo(
            db_session,
            vehiculo_id=veh.id,
            material_id=mat.id,
            cantidad=1,
        )

        r = jefe_client.get(f"{BASE}/material/{mat.id}")
        assert r.status_code == 200
        body = r.json()

        activas = body["asignaciones_activas"]
        assert len(activas) == 3
        # unidades_asignadas = 2 + 3 + 1
        assert body["unidades_asignadas"] == 6

        # Targets correctos por tipo.
        prestamos = [a for a in activas if a["tipo"] == "prestamo"]
        dotaciones = [a for a in activas if a["tipo"] == "dotacion_vehiculo"]
        assert len(prestamos) == 2
        assert len(dotaciones) == 1

        cantidades = sorted(a["cantidad"] for a in prestamos)
        assert cantidades == [2, 3]
        for a in prestamos:
            assert a["voluntario_id"] is not None
            assert a["servicio_id"] is None
            assert a["vehiculo_id"] is None
            assert "fecha_asignacion" in a

        dot = dotaciones[0]
        assert dot["vehiculo_id"] == str(veh.id)
        assert dot["voluntario_id"] is None
        assert dot["cantidad"] == 1

    def test_material_con_asignacion_servicio(
        self, jefe_client, db_session, make_material, make_servicio
    ):
        mat = make_material(tipo=TipoMaterial.SERVICIO, cantidad=5)
        servicio = make_servicio(titulo="Maratón")
        service.asignar_material_a_servicio(
            db_session,
            material_id=mat.id,
            servicio_id=servicio.id,
            cantidad=4,
        )
        r = jefe_client.get(f"{BASE}/material/{mat.id}")
        assert r.status_code == 200
        body = r.json()
        assert body["unidades_asignadas"] == 4
        assert len(body["asignaciones_activas"]) == 1
        a = body["asignaciones_activas"][0]
        assert a["tipo"] == "servicio"
        assert a["servicio_id"] == str(servicio.id)
        assert a["voluntario_id"] is None
        assert a["vehiculo_id"] is None

    def test_material_devuelto_no_aparece(
        self, jefe_client, db_session, make_material, make_voluntario
    ):
        from app.models.asignacion_material import TipoAsignacion

        mat = make_material(tipo=TipoMaterial.PRESTABLE, cantidad=5)
        vol = make_voluntario()
        service.asignar_material_a_voluntario(
            db_session,
            material_id=mat.id,
            voluntario_id=vol.id,
            tipo=TipoAsignacion.PRESTAMO,
            cantidad=2,
        )
        service.devolver_material(
            db_session, material_id=mat.id, voluntario_id=vol.id
        )
        r = jefe_client.get(f"{BASE}/material/{mat.id}")
        assert r.status_code == 200
        body = r.json()
        assert body["asignaciones_activas"] == []
        assert body["unidades_asignadas"] == 0


# ---------------------------------------------------------------------------
# Vehículo — asignacion_actual (detalle)
# ---------------------------------------------------------------------------


class TestVehiculoTrazabilidadDetalle:
    def test_vehiculo_sin_servicio_es_none(self, jefe_client, vehiculo):
        r = jefe_client.get(f"{BASE}/vehiculos/{vehiculo.id}")
        assert r.status_code == 200
        assert r.json()["asignacion_actual"] is None

    def test_vehiculo_con_servicio_activo(
        self, jefe_client, db_session, make_vehiculo, make_servicio
    ):
        veh = make_vehiculo()
        servicio = make_servicio(titulo="Operativo nieve")
        service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=veh.id, servicio_id=servicio.id
        )
        r = jefe_client.get(f"{BASE}/vehiculos/{veh.id}")
        assert r.status_code == 200
        actual = r.json()["asignacion_actual"]
        assert actual is not None
        assert actual["tipo"] == "servicio"
        assert actual["servicio_id"] == str(servicio.id)
        assert actual["servicio_titulo"] == "Operativo nieve"
        assert "fecha_asignacion" in actual

    def test_vehiculo_servicio_cerrado_vuelve_a_none(
        self, jefe_client, db_session, make_vehiculo, make_servicio
    ):
        from datetime import datetime

        veh = make_vehiculo()
        servicio = make_servicio(titulo="Servicio cerrado")
        service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=veh.id, servicio_id=servicio.id
        )
        service.liberar_asignaciones_de_servicio(
            db_session, servicio_id=servicio.id, cuando=datetime.now()
        )
        r = jefe_client.get(f"{BASE}/vehiculos/{veh.id}")
        assert r.status_code == 200
        assert r.json()["asignacion_actual"] is None


# ---------------------------------------------------------------------------
# Listado: no expone los campos de detalle y no dispara N+1
# ---------------------------------------------------------------------------


class TestListadoSinTrazabilidad:
    def test_summary_material_no_incluye_campos(self, jefe_client, material):
        r = jefe_client.get(f"{BASE}/material")
        assert r.status_code == 200
        item = r.json()[0]
        assert "asignaciones_activas" not in item
        assert "unidades_asignadas" not in item

    def test_summary_vehiculo_no_incluye_campos(self, jefe_client, vehiculo):
        r = jefe_client.get(f"{BASE}/vehiculos")
        assert r.status_code == 200
        item = r.json()[0]
        assert "asignacion_actual" not in item

    def test_listado_material_no_dispara_n_mas_uno(
        self,
        db_session,
        make_material,
        make_voluntario,
    ):
        from app.models.asignacion_material import TipoAsignacion
        from app.repositories import inventario as repo

        # 5 materiales, cada uno con una asignación activa: si el listado
        # cargase las asignaciones por fila habría N+1.
        for i in range(5):
            mat = make_material(
                nombre=f"Mat {i}", tipo=TipoMaterial.PRESTABLE, cantidad=5
            )
            vol = make_voluntario(nombre=f"Vol {i}")
            service.asignar_material_a_voluntario(
                db_session,
                material_id=mat.id,
                voluntario_id=vol.id,
                tipo=TipoAsignacion.PRESTAMO,
                cantidad=1,
            )

        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        statements: list[str] = []

        def _before_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(Engine, "before_cursor_execute", _before_cursor_execute)
        try:
            items, total = repo.list_materiales(db_session)
        finally:
            event.remove(Engine, "before_cursor_execute", _before_cursor_execute)

        assert total == 5
        assert len(items) == 5
        # Exactamente 2 SELECT: el COUNT del total y el SELECT de items.
        # Ninguna query extra por fila para cargar asignaciones.
        assert len(statements) == 2, (
            f"esperaba 2 SELECT (total + items), hubo {len(statements)}: "
            + "\n---\n".join(statements)
        )

    def test_listado_vehiculo_no_dispara_n_mas_uno(
        self,
        db_session,
        make_vehiculo,
        make_servicio,
    ):
        from app.repositories import inventario as repo

        for i in range(5):
            veh = make_vehiculo(codigo_interno=f"VH-N1-{i:04d}")
            servicio = make_servicio(titulo=f"Servicio {i}")
            service.asignar_vehiculo_a_servicio(
                db_session, vehiculo_id=veh.id, servicio_id=servicio.id
            )

        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        statements: list[str] = []

        def _before_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(Engine, "before_cursor_execute", _before_cursor_execute)
        try:
            items, total = repo.list_vehiculos(db_session)
        finally:
            event.remove(Engine, "before_cursor_execute", _before_cursor_execute)

        assert total == 5
        assert len(items) == 5
        assert len(statements) == 2, (
            f"esperaba 2 SELECT (total + items), hubo {len(statements)}: "
            + "\n---\n".join(statements)
        )


# ---------------------------------------------------------------------------
# Repo helpers de trazabilidad (selectinload del detalle)
# ---------------------------------------------------------------------------


class TestRepoTrazabilidad:
    def test_get_asignacion_activa_vehiculo_con_servicio_sin_n_mas_uno(
        self, db_session, make_vehiculo, make_servicio
    ):
        from app.repositories import inventario as repo

        veh = make_vehiculo()
        servicio = make_servicio(titulo="Con join")
        service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=veh.id, servicio_id=servicio.id
        )
        db_session.expire_all()

        # Fase 1: la consulta del helper precarga el servicio (selectinload).
        asignacion = repo.get_asignacion_activa_vehiculo_con_servicio(
            db_session, veh.id
        )

        # Fase 2: acceder al título NO debe disparar ninguna query extra:
        # el servicio ya viaja precargado en la asignación.
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        statements: list[str] = []

        def _before_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(Engine, "before_cursor_execute", _before_cursor_execute)
        try:
            titulo = asignacion.servicio.titulo
        finally:
            event.remove(Engine, "before_cursor_execute", _before_cursor_execute)

        assert titulo == "Con join"
        assert len(statements) == 0, (
            "acceder a servicio.titulo no debe disparar queries (selectinload); "
            f"hubo {len(statements)}: " + "\n---\n".join(statements)
        )

    def test_vehiculo_inexistente_no_falla_listado(self, jefe_client):
        r = jefe_client.get(f"{BASE}/vehiculos/{uuid.uuid4()}")
        assert r.status_code == 404
