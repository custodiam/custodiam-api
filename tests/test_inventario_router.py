"""Tests E2E del router de inventario (EN-05-02 + EN-05-03 + EN-05-04)."""

from __future__ import annotations

import uuid

import pytest

BASE = "/api/v1/inventario"


# ---------------------------------------------------------------------------
# Anónimo: 401
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", f"{BASE}/material"),
        ("get", f"{BASE}/material/{uuid.uuid4()}"),
        ("post", f"{BASE}/material"),
        ("patch", f"{BASE}/material/{uuid.uuid4()}"),
        ("post", f"{BASE}/material/{uuid.uuid4()}/incidencia"),
        ("post", f"{BASE}/material/{uuid.uuid4()}/reparar"),
        ("post", f"{BASE}/material/{uuid.uuid4()}/asignar"),
        ("post", f"{BASE}/material/{uuid.uuid4()}/devolver"),
        ("get", f"{BASE}/vehiculos"),
        ("get", f"{BASE}/vehiculos/{uuid.uuid4()}"),
        ("post", f"{BASE}/vehiculos"),
        ("patch", f"{BASE}/vehiculos/{uuid.uuid4()}"),
        ("post", f"{BASE}/vehiculos/{uuid.uuid4()}/incidencia"),
        ("post", f"{BASE}/vehiculos/{uuid.uuid4()}/reparar"),
    ],
)
def test_endpoints_sin_token_devuelven_401(client, method, path):
    request = getattr(client, method)
    response = request(path) if method == "get" else request(path, json={})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Material — CRUD básico
# ---------------------------------------------------------------------------


class TestMaterialListAndDetail:
    def test_lista_vacia(self, jefe_client):
        r = jefe_client.get(f"{BASE}/material")
        assert r.status_code == 200
        assert r.json() == []
        assert r.headers["X-Total-Count"] == "0"

    def test_lista_devuelve_items_y_total(self, jefe_client, make_material):
        make_material(nombre="Casco")
        make_material(nombre="Botas")
        r = jefe_client.get(f"{BASE}/material")
        assert r.status_code == 200
        assert r.headers["X-Total-Count"] == "2"

    def test_filtro_tipo(self, jefe_client, make_material):
        from app.models.material import TipoMaterial

        make_material(nombre="Cono", tipo=TipoMaterial.SERVICIO)
        make_material(nombre="Casco", tipo=TipoMaterial.PERSONAL)
        r = jefe_client.get(f"{BASE}/material", params={"tipo": "servicio"})
        assert r.status_code == 200
        nombres = [m["nombre"] for m in r.json()]
        assert nombres == ["Cono"]

    def test_filtro_q_por_codigo(self, jefe_client, make_material):
        make_material(codigo="UNICO-XYZ")
        r = jefe_client.get(f"{BASE}/material", params={"q": "unico-xyz"})
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_obtener_existente(self, jefe_client, material):
        r = jefe_client.get(f"{BASE}/material/{material.id}")
        assert r.status_code == 200
        assert r.json()["id"] == str(material.id)

    def test_obtener_inexistente_es_404(self, jefe_client):
        r = jefe_client.get(f"{BASE}/material/{uuid.uuid4()}")
        assert r.status_code == 404

    def test_voluntario_basico_no_puede_listar(self, authenticated_client):
        # Voluntario básico NO tiene `inventario.ver`.
        r = authenticated_client.get(f"{BASE}/material")
        assert r.status_code == 403


class TestMaterialCrear:
    def _payload(self, **overrides):
        base = dict(
            nombre="Material nuevo",
            tipo="personal",
            cantidad=1,
            ubicacion_base="Base",
        )
        base.update(overrides)
        return base

    def test_alta_como_jefe_devuelve_201_y_codigo_auto(
        self, client_for_role
    ):
        c = client_for_role(["jefe_equipo"])
        r = c.post(f"{BASE}/material", json=self._payload())
        assert r.status_code == 201
        body = r.json()
        assert body["codigo"].startswith("MAT-")
        assert body["estado"] == "operativo"

    def test_alta_respeta_codigo_explicito(self, client_for_role):
        c = client_for_role(["jefe_equipo"])
        r = c.post(
            f"{BASE}/material", json=self._payload(codigo="CUSTOM-001")
        )
        assert r.status_code == 201
        assert r.json()["codigo"] == "CUSTOM-001"

    def test_alta_como_voluntario_basico_es_403(self, authenticated_client):
        r = authenticated_client.post(f"{BASE}/material", json=self._payload())
        assert r.status_code == 403

    def test_alta_como_secretario_funciona(self, client_for_role):
        c = client_for_role(["secretario"])
        r = c.post(f"{BASE}/material", json=self._payload())
        assert r.status_code == 201

    def test_alta_como_tesorero_es_403(self, client_for_role):
        c = client_for_role(["tesorero"])
        r = c.post(f"{BASE}/material", json=self._payload())
        assert r.status_code == 403


class TestMaterialPatch:
    def test_patch_actualiza_campos(self, client_for_role, material):
        c = client_for_role(["jefe_equipo"])
        r = c.patch(
            f"{BASE}/material/{material.id}",
            json={"ubicacion_base": "Garaje 2"},
        )
        assert r.status_code == 200
        assert r.json()["ubicacion_base"] == "Garaje 2"

    def test_patch_inexistente_es_404(self, client_for_role):
        c = client_for_role(["jefe_equipo"])
        r = c.patch(
            f"{BASE}/material/{uuid.uuid4()}", json={"ubicacion_base": "x"}
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Material — Incidencias y reparación (CU-24)
# ---------------------------------------------------------------------------


class TestIncidencia:
    def test_voluntario_basico_puede_reportar(
        self, authenticated_client, material
    ):
        # Cualquiera con `inventario.reportar_incidencia` puede.
        r = authenticated_client.post(
            f"{BASE}/material/{material.id}/incidencia",
            json={"tipo": "averiado", "descripcion": "Correa rota"},
        )
        assert r.status_code == 200
        assert r.json()["estado"] == "averiado"

    def test_estado_operativo_es_422(self, authenticated_client, material):
        r = authenticated_client.post(
            f"{BASE}/material/{material.id}/incidencia",
            json={"tipo": "operativo", "descripcion": "x"},
        )
        assert r.status_code == 422

    def test_material_perdido_es_409(
        self, authenticated_client, make_material
    ):
        from app.models.material import EstadoInventario

        m = make_material(estado=EstadoInventario.PERDIDO)
        r = authenticated_client.post(
            f"{BASE}/material/{m.id}/incidencia",
            json={"tipo": "averiado", "descripcion": "x"},
        )
        assert r.status_code == 409

    def test_inexistente_es_404(self, authenticated_client):
        r = authenticated_client.post(
            f"{BASE}/material/{uuid.uuid4()}/incidencia",
            json={"tipo": "averiado", "descripcion": "x"},
        )
        assert r.status_code == 404


class TestReparar:
    def test_reparar_vuelve_a_operativo(self, client_for_role, make_material):
        from app.models.material import EstadoInventario

        c = client_for_role(["jefe_equipo"])
        m = make_material(estado=EstadoInventario.AVERIADO)
        r = c.post(f"{BASE}/material/{m.id}/reparar")
        assert r.status_code == 200
        assert r.json()["estado"] == "operativo"

    def test_voluntario_basico_no_puede_reparar(
        self, authenticated_client, make_material
    ):
        from app.models.material import EstadoInventario

        m = make_material(estado=EstadoInventario.AVERIADO)
        r = authenticated_client.post(f"{BASE}/material/{m.id}/reparar")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Material — Asignar a voluntario (CU-21)
# ---------------------------------------------------------------------------


class TestAsignarMaterialAVoluntario:
    def test_asignar_personal_como_jefe_seccion(
        self, client_for_role, voluntario, make_material
    ):
        from app.models.material import TipoMaterial

        c = client_for_role(["jefe_seccion"])
        m = make_material(tipo=TipoMaterial.PERSONAL, cantidad=1)
        r = c.post(
            f"{BASE}/material/{m.id}/asignar",
            json={
                "voluntario_id": str(voluntario.id),
                "tipo": "personal",
                "cantidad": 1,
            },
        )
        assert r.status_code == 201

    def test_asignar_personal_como_jefe_equipo_es_403(
        self, client_for_role, voluntario, make_material
    ):
        # jefe_equipo NO tiene `inventario.asignar_equipamiento_personal`
        # (corte sube a jefe_seccion+ por decisión 10 del RBAC).
        from app.models.material import TipoMaterial

        c = client_for_role(["jefe_equipo"])
        m = make_material(tipo=TipoMaterial.PERSONAL, cantidad=1)
        r = c.post(
            f"{BASE}/material/{m.id}/asignar",
            json={
                "voluntario_id": str(voluntario.id),
                "tipo": "personal",
                "cantidad": 1,
            },
        )
        assert r.status_code == 403

    def test_asignar_prestamo_como_jefe_equipo_funciona(
        self, client_for_role, voluntario, make_material
    ):
        # jefe_equipo SÍ tiene `inventario.prestar_temporal`.
        from app.models.material import TipoMaterial

        c = client_for_role(["jefe_equipo"])
        m = make_material(tipo=TipoMaterial.PRESTABLE, cantidad=5)
        r = c.post(
            f"{BASE}/material/{m.id}/asignar",
            json={
                "voluntario_id": str(voluntario.id),
                "tipo": "prestamo",
                "cantidad": 1,
            },
        )
        assert r.status_code == 201

    def test_asignar_tipo_no_compatible_es_409(
        self, client_for_role, voluntario, make_material
    ):
        from app.models.material import TipoMaterial

        c = client_for_role(["jefe_seccion"])
        m = make_material(tipo=TipoMaterial.SERVICIO, cantidad=10)
        r = c.post(
            f"{BASE}/material/{m.id}/asignar",
            json={
                "voluntario_id": str(voluntario.id),
                "tipo": "personal",
                "cantidad": 1,
            },
        )
        assert r.status_code == 409

    def test_asignar_inexistente_es_404(
        self, client_for_role, voluntario
    ):
        c = client_for_role(["jefe_seccion"])
        r = c.post(
            f"{BASE}/material/{uuid.uuid4()}/asignar",
            json={
                "voluntario_id": str(voluntario.id),
                "tipo": "personal",
                "cantidad": 1,
            },
        )
        assert r.status_code == 404


class TestDevolver:
    def test_devolver_funciona(
        self, client_for_role, voluntario, make_material, db_session
    ):
        from datetime import datetime

        from app.models.asignacion_material import (
            AsignacionMaterial,
            TipoAsignacion,
        )
        from app.models.material import EstadoInventario, TipoMaterial

        c = client_for_role(["jefe_equipo"])
        m = make_material(
            tipo=TipoMaterial.PERSONAL,
            cantidad=1,
            estado=EstadoInventario.EN_USO,
        )
        db_session.add(
            AsignacionMaterial(
                material_id=m.id,
                voluntario_id=voluntario.id,
                tipo=TipoAsignacion.PERSONAL,
                cantidad=1,
                fecha_asignacion=datetime(2026, 6, 1, 9, 0),
            )
        )
        db_session.commit()

        r = c.post(
            f"{BASE}/material/{m.id}/devolver",
            json={"voluntario_id": str(voluntario.id), "observaciones": "OK"},
        )
        assert r.status_code == 200
        assert r.json()["fecha_devolucion"] is not None

    def test_devolver_sin_asignacion_es_404(
        self, client_for_role, voluntario, material
    ):
        c = client_for_role(["jefe_equipo"])
        r = c.post(
            f"{BASE}/material/{material.id}/devolver",
            json={"voluntario_id": str(voluntario.id)},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Vehículos
# ---------------------------------------------------------------------------


class TestVehiculos:
    def test_listar_vehiculos(self, jefe_client, make_vehiculo):
        make_vehiculo(codigo_interno="VH-001")
        r = jefe_client.get(f"{BASE}/vehiculos")
        assert r.status_code == 200
        assert r.headers["X-Total-Count"] == "1"

    def test_obtener_vehiculo(self, jefe_client, vehiculo):
        r = jefe_client.get(f"{BASE}/vehiculos/{vehiculo.id}")
        assert r.status_code == 200

    def test_alta_vehiculo_como_jefe_unidad(self, client_for_role):
        c = client_for_role(["jefe_unidad"])
        r = c.post(
            f"{BASE}/vehiculos",
            json={
                "codigo_interno": "VH-100",
                "matricula": "1234-AAA",
                "tipo": "furgoneta",
                "ubicacion_base": "Base",
            },
        )
        assert r.status_code == 201

    def test_alta_vehiculo_como_jefe_equipo_es_403(self, client_for_role):
        # jefe_equipo NO tiene `inventario.registrar_vehiculo` (decisión 9 RBAC).
        c = client_for_role(["jefe_equipo"])
        r = c.post(
            f"{BASE}/vehiculos",
            json={
                "codigo_interno": "VH-101",
                "matricula": "2222-BBB",
                "tipo": "furgoneta",
                "ubicacion_base": "Base",
            },
        )
        assert r.status_code == 403

    def test_incidencia_vehiculo(self, authenticated_client, vehiculo):
        r = authenticated_client.post(
            f"{BASE}/vehiculos/{vehiculo.id}/incidencia",
            json={"tipo": "averiado", "descripcion": "Embrague"},
        )
        assert r.status_code == 200
        assert r.json()["estado"] == "averiado"


# ---------------------------------------------------------------------------
# Asignar a servicio (CU-22)
# ---------------------------------------------------------------------------


class TestAsignarServicio:
    def _path_material(self, servicio_id):
        return f"/api/v1/servicios/{servicio_id}/inventario/material"

    def _path_vehiculo(self, servicio_id):
        return f"/api/v1/servicios/{servicio_id}/inventario/vehiculo"

    def test_asignar_material_a_servicio(
        self, client_for_role, servicio_publicado, make_material
    ):
        from app.models.material import TipoMaterial

        c = client_for_role(["jefe_equipo"])
        m = make_material(tipo=TipoMaterial.SERVICIO, cantidad=10)
        r = c.post(
            self._path_material(servicio_publicado.id),
            json={"material_id": str(m.id), "cantidad": 3},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["cantidad"] == 3
        assert body["voluntario_id"] is None
        assert body["servicio_id"] == str(servicio_publicado.id)

    def test_asignar_vehiculo_a_servicio(
        self, client_for_role, servicio_publicado, vehiculo
    ):
        c = client_for_role(["jefe_equipo"])
        r = c.post(
            self._path_vehiculo(servicio_publicado.id),
            json={"vehiculo_id": str(vehiculo.id)},
        )
        assert r.status_code == 201

    def test_asignar_vehiculo_ya_asignado_es_409(
        self, client_for_role, servicio_publicado, make_servicio, vehiculo
    ):
        from app.models.servicio import EstadoServicio

        c = client_for_role(["jefe_equipo"])
        otro = make_servicio(estado=EstadoServicio.PUBLICADO)
        c.post(
            self._path_vehiculo(servicio_publicado.id),
            json={"vehiculo_id": str(vehiculo.id)},
        )
        r = c.post(
            self._path_vehiculo(otro.id),
            json={"vehiculo_id": str(vehiculo.id)},
        )
        assert r.status_code == 409

    def test_secretario_no_puede_asignar_a_servicio(
        self, client_for_role, servicio_publicado, make_material
    ):
        # secretario NO tiene `inventario.asignar_a_servicio`.
        from app.models.material import TipoMaterial

        c = client_for_role(["secretario"])
        m = make_material(tipo=TipoMaterial.SERVICIO, cantidad=10)
        r = c.post(
            self._path_material(servicio_publicado.id),
            json={"material_id": str(m.id), "cantidad": 1},
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# E2E US-05-06/07: cerrar servicio libera asignaciones
# ---------------------------------------------------------------------------


class TestRouterEdgeCases:
    """Cubre los caminos de excepción menos comunes."""

    def test_reparar_material_inexistente_es_404(self, client_for_role):
        c = client_for_role(["jefe_equipo"])
        r = c.post(f"{BASE}/material/{uuid.uuid4()}/reparar")
        assert r.status_code == 404

    def test_reparar_material_perdido_es_409(
        self, client_for_role, make_material
    ):
        from app.models.material import EstadoInventario

        c = client_for_role(["jefe_equipo"])
        m = make_material(estado=EstadoInventario.PERDIDO)
        r = c.post(f"{BASE}/material/{m.id}/reparar")
        assert r.status_code == 409

    def test_asignar_material_no_operativo_es_409(
        self, client_for_role, voluntario, make_material
    ):
        from app.models.material import EstadoInventario, TipoMaterial

        c = client_for_role(["jefe_seccion"])
        m = make_material(
            tipo=TipoMaterial.PERSONAL, estado=EstadoInventario.AVERIADO
        )
        r = c.post(
            f"{BASE}/material/{m.id}/asignar",
            json={
                "voluntario_id": str(voluntario.id),
                "tipo": "personal",
                "cantidad": 1,
            },
        )
        assert r.status_code == 409

    def test_asignar_material_dobla_es_409(
        self, client_for_role, voluntario, make_material
    ):
        from app.models.material import TipoMaterial

        c = client_for_role(["jefe_equipo"])
        m = make_material(tipo=TipoMaterial.PRESTABLE, cantidad=5)
        c.post(
            f"{BASE}/material/{m.id}/asignar",
            json={
                "voluntario_id": str(voluntario.id),
                "tipo": "prestamo",
                "cantidad": 1,
            },
        )
        r = c.post(
            f"{BASE}/material/{m.id}/asignar",
            json={
                "voluntario_id": str(voluntario.id),
                "tipo": "prestamo",
                "cantidad": 1,
            },
        )
        assert r.status_code == 409

    def test_asignar_material_sin_stock_es_409(
        self, client_for_role, voluntario, make_voluntario, make_material
    ):
        from app.models.material import TipoMaterial

        c = client_for_role(["jefe_equipo"])
        m = make_material(tipo=TipoMaterial.PRESTABLE, cantidad=1)
        otro = make_voluntario(nombre="Otro")
        c.post(
            f"{BASE}/material/{m.id}/asignar",
            json={
                "voluntario_id": str(voluntario.id),
                "tipo": "prestamo",
                "cantidad": 1,
            },
        )
        r = c.post(
            f"{BASE}/material/{m.id}/asignar",
            json={
                "voluntario_id": str(otro.id),
                "tipo": "prestamo",
                "cantidad": 1,
            },
        )
        assert r.status_code == 409

    def test_devolver_material_inexistente_es_404(
        self, client_for_role, voluntario
    ):
        c = client_for_role(["jefe_equipo"])
        r = c.post(
            f"{BASE}/material/{uuid.uuid4()}/devolver",
            json={"voluntario_id": str(voluntario.id)},
        )
        assert r.status_code == 404

    def test_obtener_vehiculo_inexistente_es_404(self, jefe_client):
        r = jefe_client.get(f"{BASE}/vehiculos/{uuid.uuid4()}")
        assert r.status_code == 404

    def test_patch_vehiculo_funciona(self, client_for_role, vehiculo):
        c = client_for_role(["jefe_unidad"])
        r = c.patch(
            f"{BASE}/vehiculos/{vehiculo.id}",
            json={"marca_modelo": "Renault Master"},
        )
        assert r.status_code == 200
        assert r.json()["marca_modelo"] == "Renault Master"

    def test_patch_vehiculo_inexistente_es_404(self, client_for_role):
        c = client_for_role(["jefe_unidad"])
        r = c.patch(
            f"{BASE}/vehiculos/{uuid.uuid4()}", json={"marca_modelo": "x"}
        )
        assert r.status_code == 404

    def test_incidencia_vehiculo_estado_invalido_es_422(
        self, authenticated_client, vehiculo
    ):
        r = authenticated_client.post(
            f"{BASE}/vehiculos/{vehiculo.id}/incidencia",
            json={"tipo": "operativo", "descripcion": "x"},
        )
        assert r.status_code == 422

    def test_incidencia_vehiculo_inexistente_es_404(
        self, authenticated_client
    ):
        r = authenticated_client.post(
            f"{BASE}/vehiculos/{uuid.uuid4()}/incidencia",
            json={"tipo": "averiado", "descripcion": "x"},
        )
        assert r.status_code == 404

    def test_incidencia_vehiculo_perdido_es_409(
        self, authenticated_client, make_vehiculo
    ):
        from app.models.material import EstadoInventario

        v = make_vehiculo(estado=EstadoInventario.PERDIDO)
        r = authenticated_client.post(
            f"{BASE}/vehiculos/{v.id}/incidencia",
            json={"tipo": "averiado", "descripcion": "x"},
        )
        assert r.status_code == 409

    def test_reparar_vehiculo_funciona(self, client_for_role, make_vehiculo):
        from app.models.material import EstadoInventario

        c = client_for_role(["jefe_unidad"])
        v = make_vehiculo(estado=EstadoInventario.AVERIADO)
        r = c.post(f"{BASE}/vehiculos/{v.id}/reparar")
        assert r.status_code == 200
        assert r.json()["estado"] == "operativo"

    def test_reparar_vehiculo_inexistente_es_404(self, client_for_role):
        c = client_for_role(["jefe_unidad"])
        r = c.post(f"{BASE}/vehiculos/{uuid.uuid4()}/reparar")
        assert r.status_code == 404

    def test_reparar_vehiculo_perdido_es_409(
        self, client_for_role, make_vehiculo
    ):
        from app.models.material import EstadoInventario

        c = client_for_role(["jefe_unidad"])
        v = make_vehiculo(estado=EstadoInventario.PERDIDO)
        r = c.post(f"{BASE}/vehiculos/{v.id}/reparar")
        assert r.status_code == 409

    def test_asignar_material_a_servicio_inexistente_es_404(
        self, client_for_role, servicio_publicado
    ):
        c = client_for_role(["jefe_equipo"])
        r = c.post(
            f"/api/v1/servicios/{servicio_publicado.id}/inventario/material",
            json={"material_id": str(uuid.uuid4()), "cantidad": 1},
        )
        assert r.status_code == 404

    def test_asignar_material_a_servicio_tipo_no_compatible_es_409(
        self, client_for_role, servicio_publicado, make_material
    ):
        from app.models.material import TipoMaterial

        c = client_for_role(["jefe_equipo"])
        m = make_material(tipo=TipoMaterial.PERSONAL, cantidad=1)
        r = c.post(
            f"/api/v1/servicios/{servicio_publicado.id}/inventario/material",
            json={"material_id": str(m.id), "cantidad": 1},
        )
        assert r.status_code == 409

    def test_asignar_material_a_servicio_sin_stock_es_409(
        self, client_for_role, servicio_publicado, make_material
    ):
        from app.models.material import TipoMaterial

        c = client_for_role(["jefe_equipo"])
        m = make_material(tipo=TipoMaterial.SERVICIO, cantidad=2)
        r = c.post(
            f"/api/v1/servicios/{servicio_publicado.id}/inventario/material",
            json={"material_id": str(m.id), "cantidad": 5},
        )
        assert r.status_code == 409

    def test_asignar_vehiculo_inexistente_es_404(
        self, client_for_role, servicio_publicado
    ):
        c = client_for_role(["jefe_equipo"])
        r = c.post(
            f"/api/v1/servicios/{servicio_publicado.id}/inventario/vehiculo",
            json={"vehiculo_id": str(uuid.uuid4())},
        )
        assert r.status_code == 404

    def test_asignar_vehiculo_no_operativo_es_409(
        self, client_for_role, servicio_publicado, make_vehiculo
    ):
        from app.models.material import EstadoInventario

        c = client_for_role(["jefe_equipo"])
        v = make_vehiculo(estado=EstadoInventario.AVERIADO)
        r = c.post(
            f"/api/v1/servicios/{servicio_publicado.id}/inventario/vehiculo",
            json={"vehiculo_id": str(v.id)},
        )
        assert r.status_code == 409


class TestCerrarServicioLiberaInventario:
    def test_cerrar_servicio_libera_material_y_vehiculo_e2e(
        self,
        client_for_role,
        servicio_activo,
        make_servicio,
        make_material,
        vehiculo,
    ):
        """E2E completo de US-05-06 / US-05-07.

        Asigna material y vehículo al servicio activo, cierra el servicio
        y verifica que (a) las asignaciones del servicio cerrado dejaron
        de bloquear el vehículo (reasignación a OTRO servicio funciona —
        solo es posible si la primera asignación está cerrada), y (b) el
        material vuelve a estar disponible para otro servicio.
        """

        from app.models.material import TipoMaterial
        from app.models.servicio import EstadoServicio

        jefe = client_for_role(["jefe_equipo"])
        mat = make_material(tipo=TipoMaterial.SERVICIO, cantidad=5)

        r1 = jefe.post(
            f"/api/v1/servicios/{servicio_activo.id}/inventario/material",
            json={"material_id": str(mat.id), "cantidad": 2},
        )
        assert r1.status_code == 201
        r2 = jefe.post(
            f"/api/v1/servicios/{servicio_activo.id}/inventario/vehiculo",
            json={"vehiculo_id": str(vehiculo.id)},
        )
        assert r2.status_code == 201

        # Cerrar el servicio (E03) → libera inventario (US-05-06 + US-05-07).
        r3 = jefe.post(f"/api/v1/servicios/{servicio_activo.id}/cerrar")
        assert r3.status_code == 200

        # Invariante: como el vehículo se liberó, reasignarlo a OTRO
        # servicio activo debe funcionar (201, no 409 VehiculoYaAsignado).
        otro = make_servicio(estado=EstadoServicio.ACTIVO)
        r4 = jefe.post(
            f"/api/v1/servicios/{otro.id}/inventario/vehiculo",
            json={"vehiculo_id": str(vehiculo.id)},
        )
        assert r4.status_code == 201
