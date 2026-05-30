"""Integración inventario ↔ catálogo de ubicaciones (E10 / PR2).

Cubre el enganche del FK ``ubicacion_base_id`` introducido en PR2:

- material / vehículo pueden referenciar una ubicación del catálogo;
- un ``ubicacion_base_id`` inexistente se rechaza con 422;
- el texto ``ubicacion_base`` es ahora opcional (un activo puede tener solo
  el FK, sin etiqueta legacy);
- una ubicación en uso no se puede borrar (409).
"""

from __future__ import annotations

import uuid

import pytest

from app.models.material import TipoMaterial
from app.schemas.inventario import MaterialCreate, VehiculoCreate
from app.services import inventario as inventario_service

INV = "/api/v1/inventario"
UBI = "/api/v1/ubicaciones"


# ---------------------------------------------------------------------------
# Service: validación del FK al crear
# ---------------------------------------------------------------------------


class TestServiceValidacionFk:
    def test_crear_material_con_ubicacion_valida(self, db_session, make_ubicacion):
        ubi = make_ubicacion(nombre="Almacén central")
        material = inventario_service.crear_material(
            db_session,
            MaterialCreate(
                nombre="Botiquín", tipo=TipoMaterial.PRESTABLE, ubicacion_base_id=ubi.id
            ),
        )
        assert material.ubicacion_base_id == ubi.id

    def test_crear_material_con_ubicacion_inexistente_es_error(self, db_session):
        with pytest.raises(inventario_service.UbicacionBaseNoEncontrada):
            inventario_service.crear_material(
                db_session,
                MaterialCreate(
                    nombre="Botiquín",
                    tipo=TipoMaterial.PRESTABLE,
                    ubicacion_base_id=uuid.uuid4(),
                ),
            )

    def test_crear_material_sin_ubicacion_es_valido(self, db_session):
        # El texto y el FK son ambos opcionales tras PR2 (2B).
        material = inventario_service.crear_material(
            db_session, MaterialCreate(nombre="Suelto", tipo=TipoMaterial.PERSONAL)
        )
        assert material.ubicacion_base is None
        assert material.ubicacion_base_id is None

    def test_crear_vehiculo_con_ubicacion_inexistente_es_error(self, db_session):
        from app.models.vehiculo import TipoVehiculo

        with pytest.raises(inventario_service.UbicacionBaseNoEncontrada):
            inventario_service.crear_vehiculo(
                db_session,
                VehiculoCreate(
                    codigo_interno="VH-X1",
                    matricula="1111-AAA",
                    tipo=TipoVehiculo.FURGONETA,
                    ubicacion_base_id=uuid.uuid4(),
                ),
            )


# ---------------------------------------------------------------------------
# Router: POST con FK
# ---------------------------------------------------------------------------


class TestRouterCrearConFk:
    def test_post_material_con_ubicacion_valida_201(self, jefe_client, make_ubicacion):
        ubi = make_ubicacion(nombre="Nave 1")
        r = jefe_client.post(
            f"{INV}/material",
            json={
                "nombre": "Cono",
                "tipo": "servicio",
                "ubicacion_base_id": str(ubi.id),
            },
        )
        assert r.status_code == 201
        assert r.json()["ubicacion_base_id"] == str(ubi.id)

    def test_post_material_con_ubicacion_inexistente_422(self, jefe_client):
        r = jefe_client.post(
            f"{INV}/material",
            json={
                "nombre": "Cono",
                "tipo": "servicio",
                "ubicacion_base_id": str(uuid.uuid4()),
            },
        )
        assert r.status_code == 422

    def test_post_material_sin_ubicacion_201(self, jefe_client):
        r = jefe_client.post(
            f"{INV}/material", json={"nombre": "Cono", "tipo": "servicio"}
        )
        assert r.status_code == 201
        assert r.json()["ubicacion_base"] is None
        assert r.json()["ubicacion_base_id"] is None


# ---------------------------------------------------------------------------
# Router: borrado protegido de la ubicación en uso
# ---------------------------------------------------------------------------


class TestBorradoProtegido:
    def test_delete_ubicacion_en_uso_por_material_es_409(
        self, client_for_role, make_ubicacion, make_material
    ):
        ubi = make_ubicacion(nombre="Ocupada por material")
        make_material(ubicacion_base_id=ubi.id)
        cliente = client_for_role(["jefe_seccion"])
        r = cliente.delete(f"{UBI}/{ubi.id}")
        assert r.status_code == 409

    def test_delete_ubicacion_en_uso_por_vehiculo_es_409(
        self, client_for_role, make_ubicacion, make_vehiculo
    ):
        ubi = make_ubicacion(nombre="Ocupada por vehículo")
        make_vehiculo(ubicacion_base_id=ubi.id)
        cliente = client_for_role(["jefe_seccion"])
        r = cliente.delete(f"{UBI}/{ubi.id}")
        assert r.status_code == 409

    def test_delete_ubicacion_libre_es_204(self, client_for_role, make_ubicacion):
        ubi = make_ubicacion(nombre="Libre")
        cliente = client_for_role(["jefe_seccion"])
        r = cliente.delete(f"{UBI}/{ubi.id}")
        assert r.status_code == 204
