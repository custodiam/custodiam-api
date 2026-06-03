"""Tests de no-solape temporal de recursos (PR6 / Política A).

Cubre el bloqueo de asignación de vehículo y material a servicio por
solape de intervalo, sustituyendo el antiguo chequeo binario "ya
asignado". Política A:

1. Solape semiabierto ``[inicio, fin)``: solapan sii ``inicio_A < fin_B
   AND inicio_B < fin_A``. Encadenados (``fin_A == inicio_B``) NO solapan.
2. ``fecha_fin`` NULL no reserva (ni el existente ni el nuevo).
3. Borrador no reserva (sólo PUBLICADO / ACTIVO).
4. Emergencia hace override del bloqueo por solape.

Requiere Postgres real (contenedor 5433); no SQLite.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.models.asignacion_material import TipoAsignacion
from app.models.material import TipoMaterial
from app.models.servicio import EstadoServicio, TipoServicio
from app.services import inventario as service

# Intervalos de referencia para los tests. Bloque A: 09:00-14:00.
A_INI = datetime(2026, 6, 1, 9, 0)
A_FIN = datetime(2026, 6, 1, 14, 0)


def _servicio(make_servicio, *, inicio, fin, estado, tipo=TipoServicio.PREVENTIVO):
    return make_servicio(
        fecha_inicio=inicio, fecha_fin=fin, estado=estado, tipo=tipo
    )


# ---------------------------------------------------------------------------
# Vehículo (unidad única)
# ---------------------------------------------------------------------------


class TestSolapeVehiculo:
    def test_disjuntos_permite(self, db_session, make_servicio, vehiculo):
        # A: 09-14 (publicado, ocupa). B: 14-18 encadenado → disjunto.
        a = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=vehiculo.id, servicio_id=a.id
        )
        b = _servicio(
            make_servicio,
            inicio=datetime(2026, 6, 2, 9, 0),
            fin=datetime(2026, 6, 2, 14, 0),
            estado=EstadoServicio.PUBLICADO,
        )
        asignacion = service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=vehiculo.id, servicio_id=b.id
        )
        assert asignacion.activa is True

    def test_solape_parcial_bloquea(self, db_session, make_servicio, vehiculo):
        a = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=vehiculo.id, servicio_id=a.id
        )
        # B: 12-16 solapa parcialmente con A (09-14).
        b = _servicio(
            make_servicio,
            inicio=datetime(2026, 6, 1, 12, 0),
            fin=datetime(2026, 6, 1, 16, 0),
            estado=EstadoServicio.PUBLICADO,
        )
        with pytest.raises(service.VehiculoOcupado) as exc:
            service.asignar_vehiculo_a_servicio(
                db_session, vehiculo_id=vehiculo.id, servicio_id=b.id
            )
        assert exc.value.conflictos
        assert exc.value.conflictos[0]["servicio_id"] == a.id

    def test_borde_encadenado_no_bloquea(
        self, db_session, make_servicio, vehiculo
    ):
        # fin_A (14:00) == inicio_B (14:00) → semiabierto, NO solapan.
        a = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=vehiculo.id, servicio_id=a.id
        )
        b = _servicio(
            make_servicio,
            inicio=A_FIN,
            fin=datetime(2026, 6, 1, 18, 0),
            estado=EstadoServicio.PUBLICADO,
        )
        asignacion = service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=vehiculo.id, servicio_id=b.id
        )
        assert asignacion.activa is True

    def test_fecha_fin_null_existente_no_reserva(
        self, db_session, make_servicio, vehiculo
    ):
        # A con fecha_fin NULL no reserva: B solapante (mismo inicio) permite.
        a = _servicio(
            make_servicio, inicio=A_INI, fin=None,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=vehiculo.id, servicio_id=a.id
        )
        b = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        asignacion = service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=vehiculo.id, servicio_id=b.id
        )
        assert asignacion.activa is True

    def test_fecha_fin_null_nuevo_no_bloquea(
        self, db_session, make_servicio, vehiculo
    ):
        # A cerrado ocupa 09-14; B nuevo con fecha_fin NULL no evalúa solape.
        a = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=vehiculo.id, servicio_id=a.id
        )
        b = _servicio(
            make_servicio, inicio=A_INI, fin=None,
            estado=EstadoServicio.PUBLICADO,
        )
        asignacion = service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=vehiculo.id, servicio_id=b.id
        )
        assert asignacion.activa is True

    def test_borrador_no_reserva(self, db_session, make_servicio, vehiculo):
        # A en BORRADOR no reserva: B solapante permite.
        a = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.BORRADOR,
        )
        service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=vehiculo.id, servicio_id=a.id
        )
        b = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        asignacion = service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=vehiculo.id, servicio_id=b.id
        )
        assert asignacion.activa is True

    def test_emergencia_override_permite(
        self, db_session, make_servicio, vehiculo
    ):
        # A (preventivo, publicado) ocupa 09-14. B EMERGENCIA solapa → permite.
        a = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=vehiculo.id, servicio_id=a.id
        )
        b = _servicio(
            make_servicio,
            inicio=datetime(2026, 6, 1, 10, 0),
            fin=datetime(2026, 6, 1, 12, 0),
            estado=EstadoServicio.ACTIVO,
            tipo=TipoServicio.EMERGENCIA,
        )
        asignacion = service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=vehiculo.id, servicio_id=b.id
        )
        assert asignacion.activa is True
        # Override NO libera la asignación del preventivo (gestión humana).
        from app.repositories import inventario as repo

        activas = repo.list_asignaciones_activas_servicio_vehiculo(
            db_session, a.id
        )
        assert len(activas) == 1

    def test_servicio_inexistente_404(self, db_session, vehiculo):
        with pytest.raises(service.ServicioNoEncontrado):
            service.asignar_vehiculo_a_servicio(
                db_session, vehiculo_id=vehiculo.id, servicio_id=uuid.uuid4()
            )

    def test_vehiculo_averiado_bloquea(
        self, db_session, make_servicio, make_vehiculo
    ):
        from app.models.material import EstadoInventario

        v = make_vehiculo(estado=EstadoInventario.AVERIADO)
        a = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        with pytest.raises(service.VehiculoNoOperativo):
            service.asignar_vehiculo_a_servicio(
                db_session, vehiculo_id=v.id, servicio_id=a.id
            )


# ---------------------------------------------------------------------------
# Material (stock multi-unidad)
# ---------------------------------------------------------------------------


class TestSolapeMaterial:
    def test_disjuntos_permite_todo_el_stock(
        self, db_session, make_servicio, make_material
    ):
        # 5 unidades. A (09-14) reserva 5; B disjunto reserva 5 → permite.
        m = make_material(tipo=TipoMaterial.SERVICIO, cantidad=5)
        a = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_material_a_servicio(
            db_session, material_id=m.id, servicio_id=a.id, cantidad=5
        )
        b = _servicio(
            make_servicio,
            inicio=datetime(2026, 6, 2, 9, 0),
            fin=datetime(2026, 6, 2, 14, 0),
            estado=EstadoServicio.PUBLICADO,
        )
        asignacion = service.asignar_material_a_servicio(
            db_session, material_id=m.id, servicio_id=b.id, cantidad=5
        )
        assert asignacion.cantidad == 5

    def test_solape_sin_unidades_bloquea(
        self, db_session, make_servicio, make_material
    ):
        # 5 unidades. A solapante reserva 4; B pide 2 → 4+2 > 5 → bloquea.
        m = make_material(tipo=TipoMaterial.SERVICIO, cantidad=5)
        a = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_material_a_servicio(
            db_session, material_id=m.id, servicio_id=a.id, cantidad=4
        )
        b = _servicio(
            make_servicio,
            inicio=datetime(2026, 6, 1, 12, 0),
            fin=datetime(2026, 6, 1, 16, 0),
            estado=EstadoServicio.PUBLICADO,
        )
        with pytest.raises(service.MaterialSolapado) as exc:
            service.asignar_material_a_servicio(
                db_session, material_id=m.id, servicio_id=b.id, cantidad=2
            )
        assert exc.value.conflictos[0]["servicio_id"] == a.id

    def test_solape_con_unidades_suficientes_permite(
        self, db_session, make_servicio, make_material
    ):
        # 5 unidades. A solapante reserva 3; B pide 2 → 3+2 = 5 → permite.
        m = make_material(tipo=TipoMaterial.SERVICIO, cantidad=5)
        a = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_material_a_servicio(
            db_session, material_id=m.id, servicio_id=a.id, cantidad=3
        )
        b = _servicio(
            make_servicio,
            inicio=datetime(2026, 6, 1, 12, 0),
            fin=datetime(2026, 6, 1, 16, 0),
            estado=EstadoServicio.PUBLICADO,
        )
        asignacion = service.asignar_material_a_servicio(
            db_session, material_id=m.id, servicio_id=b.id, cantidad=2
        )
        assert asignacion.cantidad == 2

    def test_borde_encadenado_no_bloquea(
        self, db_session, make_servicio, make_material
    ):
        m = make_material(tipo=TipoMaterial.SERVICIO, cantidad=2)
        a = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_material_a_servicio(
            db_session, material_id=m.id, servicio_id=a.id, cantidad=2
        )
        b = _servicio(
            make_servicio,
            inicio=A_FIN,
            fin=datetime(2026, 6, 1, 18, 0),
            estado=EstadoServicio.PUBLICADO,
        )
        asignacion = service.asignar_material_a_servicio(
            db_session, material_id=m.id, servicio_id=b.id, cantidad=2
        )
        assert asignacion.cantidad == 2

    def test_fecha_fin_null_existente_no_reserva(
        self, db_session, make_servicio, make_material
    ):
        m = make_material(tipo=TipoMaterial.SERVICIO, cantidad=2)
        a = _servicio(
            make_servicio, inicio=A_INI, fin=None,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_material_a_servicio(
            db_session, material_id=m.id, servicio_id=a.id, cantidad=2
        )
        b = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        asignacion = service.asignar_material_a_servicio(
            db_session, material_id=m.id, servicio_id=b.id, cantidad=2
        )
        assert asignacion.cantidad == 2

    def test_fecha_fin_null_nuevo_no_bloquea(
        self, db_session, make_servicio, make_material
    ):
        m = make_material(tipo=TipoMaterial.SERVICIO, cantidad=2)
        a = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_material_a_servicio(
            db_session, material_id=m.id, servicio_id=a.id, cantidad=2
        )
        b = _servicio(
            make_servicio, inicio=A_INI, fin=None,
            estado=EstadoServicio.PUBLICADO,
        )
        asignacion = service.asignar_material_a_servicio(
            db_session, material_id=m.id, servicio_id=b.id, cantidad=2
        )
        assert asignacion.cantidad == 2

    def test_borrador_no_reserva(
        self, db_session, make_servicio, make_material
    ):
        m = make_material(tipo=TipoMaterial.SERVICIO, cantidad=2)
        a = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.BORRADOR,
        )
        service.asignar_material_a_servicio(
            db_session, material_id=m.id, servicio_id=a.id, cantidad=2
        )
        b = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        asignacion = service.asignar_material_a_servicio(
            db_session, material_id=m.id, servicio_id=b.id, cantidad=2
        )
        assert asignacion.cantidad == 2

    def test_emergencia_override_permite(
        self, db_session, make_servicio, make_material
    ):
        # A reserva las 2 únicas unidades; B EMERGENCIA solapante permite
        # pese a no quedar stock libre en el intervalo (override).
        m = make_material(tipo=TipoMaterial.SERVICIO, cantidad=2)
        a = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_material_a_servicio(
            db_session, material_id=m.id, servicio_id=a.id, cantidad=2
        )
        b = _servicio(
            make_servicio,
            inicio=datetime(2026, 6, 1, 10, 0),
            fin=datetime(2026, 6, 1, 12, 0),
            estado=EstadoServicio.ACTIVO,
            tipo=TipoServicio.EMERGENCIA,
        )
        asignacion = service.asignar_material_a_servicio(
            db_session, material_id=m.id, servicio_id=b.id, cantidad=2
        )
        assert asignacion.cantidad == 2

    def test_sin_solape_pero_sobre_stock_es_cantidad_insuficiente(
        self, db_session, make_servicio, make_material
    ):
        # Sin servicio solapante, pedir más unidades que el stock total
        # mantiene el error clásico CantidadInsuficiente (tope físico duro),
        # no MaterialSolapado (que sólo aparece cuando hay solape real).
        m = make_material(tipo=TipoMaterial.SERVICIO, cantidad=2)
        a = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        with pytest.raises(service.CantidadInsuficiente):
            service.asignar_material_a_servicio(
                db_session, material_id=m.id, servicio_id=a.id, cantidad=3
            )


# ---------------------------------------------------------------------------
# Dotación fija NO interfiere con el solape (PR3 vs PR6)
# ---------------------------------------------------------------------------


class TestDotacionNoInterfiereSolape:
    def test_dotacion_fija_no_cuenta_como_solape_vehiculo(
        self, db_session, make_servicio, make_material, vehiculo
    ):
        # La dotación fija (material→vehículo, sin servicio_id) no tiene
        # intervalo de servicio: no debe contar para el solape de vehículo.
        m = make_material(tipo=TipoMaterial.PRESTABLE, cantidad=3)
        service.asignar_dotacion_vehiculo(
            db_session, vehiculo_id=vehiculo.id, material_id=m.id, cantidad=1
        )
        a = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        # El vehículo, pese a tener dotación, sigue asignable a un servicio.
        asignacion = service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=vehiculo.id, servicio_id=a.id
        )
        assert asignacion.activa is True

    def test_dotacion_fija_no_cuenta_como_reserva_material(
        self, db_session, make_servicio, make_material, vehiculo
    ):
        # Material PRESTABLE de stock 3: 1 dotado a vehículo (global, no de
        # servicio). Un servicio SERVICIO necesita material tipo SERVICIO, así
        # que usamos otro material para el servicio. Verificamos que la
        # consulta de solape de material ignora DOTACION_VEHICULO.
        m = make_material(tipo=TipoMaterial.PRESTABLE, cantidad=3)
        service.asignar_dotacion_vehiculo(
            db_session, vehiculo_id=vehiculo.id, material_id=m.id, cantidad=1
        )
        from app.repositories import inventario as repo

        # find_solapes_material sólo mira tipo SERVICIO: la dotación no aparece.
        solapes = repo.find_solapes_material(
            db_session,
            material_id=m.id,
            inicio=A_INI,
            fin=A_FIN,
        )
        assert solapes == []


# ---------------------------------------------------------------------------
# Endpoint GET .../ocupacion
# ---------------------------------------------------------------------------


def _crear_vehiculo_via_db(db_session, **kw):
    from app.models.vehiculo import TipoVehiculo, Vehiculo

    v = Vehiculo(
        codigo_interno=kw.get("codigo_interno", "VH-OCU-1"),
        matricula="9999-ZZZ",
        tipo=TipoVehiculo.FURGONETA,
        ubicacion_base="Base",
    )
    db_session.add(v)
    db_session.commit()
    db_session.refresh(v)
    return v


class TestEndpointOcupacion:
    def test_vehiculo_libre_devuelve_disponible(
        self, jefe_client, db_session, vehiculo
    ):
        r = jefe_client.get(
            f"/api/v1/inventario/vehiculos/{vehiculo.id}/ocupacion",
            params={"desde": A_INI.isoformat(), "hasta": A_FIN.isoformat()},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["disponible"] is True
        assert body["conflictos"] == []

    def test_vehiculo_ocupado_devuelve_conflictos(
        self, jefe_client, db_session, make_servicio, vehiculo
    ):
        a = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=vehiculo.id, servicio_id=a.id
        )
        r = jefe_client.get(
            f"/api/v1/inventario/vehiculos/{vehiculo.id}/ocupacion",
            params={
                "desde": datetime(2026, 6, 1, 12, 0).isoformat(),
                "hasta": datetime(2026, 6, 1, 16, 0).isoformat(),
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["disponible"] is False
        assert len(body["conflictos"]) == 1
        assert body["conflictos"][0]["servicio_id"] == str(a.id)

    def test_excluir_servicio_propio(
        self, jefe_client, db_session, make_servicio, vehiculo
    ):
        # Si excluimos el único servicio en conflicto, queda disponible.
        a = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=vehiculo.id, servicio_id=a.id
        )
        r = jefe_client.get(
            f"/api/v1/inventario/vehiculos/{vehiculo.id}/ocupacion",
            params={
                "desde": A_INI.isoformat(),
                "hasta": A_FIN.isoformat(),
                "excluir_servicio_id": str(a.id),
            },
        )
        assert r.status_code == 200
        assert r.json()["disponible"] is True

    def test_rango_invalido_422(self, jefe_client, vehiculo):
        r = jefe_client.get(
            f"/api/v1/inventario/vehiculos/{vehiculo.id}/ocupacion",
            params={"desde": A_FIN.isoformat(), "hasta": A_INI.isoformat()},
        )
        assert r.status_code == 422

    def test_vehiculo_inexistente_404(self, jefe_client):
        r = jefe_client.get(
            f"/api/v1/inventario/vehiculos/{uuid.uuid4()}/ocupacion",
            params={"desde": A_INI.isoformat(), "hasta": A_FIN.isoformat()},
        )
        assert r.status_code == 404

    def test_material_disponible_con_stock(
        self, jefe_client, db_session, make_servicio, make_material
    ):
        m = make_material(tipo=TipoMaterial.SERVICIO, cantidad=5)
        a = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_material_a_servicio(
            db_session, material_id=m.id, servicio_id=a.id, cantidad=3
        )
        # Solapante, pero quedan 2 → disponible para 2.
        r = jefe_client.get(
            f"/api/v1/inventario/material/{m.id}/ocupacion",
            params={
                "desde": datetime(2026, 6, 1, 12, 0).isoformat(),
                "hasta": datetime(2026, 6, 1, 16, 0).isoformat(),
                "cantidad": 2,
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["disponible"] is True
        assert len(body["conflictos"]) == 1

    def test_material_no_disponible_sin_stock(
        self, jefe_client, db_session, make_servicio, make_material
    ):
        m = make_material(tipo=TipoMaterial.SERVICIO, cantidad=5)
        a = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_material_a_servicio(
            db_session, material_id=m.id, servicio_id=a.id, cantidad=4
        )
        r = jefe_client.get(
            f"/api/v1/inventario/material/{m.id}/ocupacion",
            params={
                "desde": datetime(2026, 6, 1, 12, 0).isoformat(),
                "hasta": datetime(2026, 6, 1, 16, 0).isoformat(),
                "cantidad": 2,
            },
        )
        assert r.status_code == 200
        assert r.json()["disponible"] is False


# ---------------------------------------------------------------------------
# Filtro de disponibilidad en el listado (picker del frontend)
# ---------------------------------------------------------------------------
#
# El listado de inventario admite `disponible_para_servicio=<uuid>`: con él,
# devuelve SOLO los recursos disponibles para ese servicio en su intervalo,
# reutilizando la Política A. Aquí se prueba a nivel de service (la lógica de
# filtrado) y de router (el query param + el 404 del servicio destino).


class TestServicioVehiculosDisponibles:
    def test_vehiculo_comprometido_en_solape_no_aparece_y_libre_si(
        self, db_session, make_servicio, make_vehiculo
    ):
        # `ocupado` está asignado a un servicio que solapa el destino → fuera.
        # `libre` no tiene asignación alguna → dentro.
        ocupado = make_vehiculo(codigo_interno="VH-OCU")
        libre = make_vehiculo(codigo_interno="VH-LIB")
        bloqueante = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=ocupado.id, servicio_id=bloqueante.id
        )
        # Destino: 12-16, solapa con el bloqueante (09-14).
        destino = _servicio(
            make_servicio,
            inicio=datetime(2026, 6, 1, 12, 0),
            fin=datetime(2026, 6, 1, 16, 0),
            estado=EstadoServicio.BORRADOR,
        )

        items, total = service.listar_vehiculos_disponibles_para_servicio(
            db_session, servicio_id=destino.id
        )
        ids = {v.id for v in items}
        assert libre.id in ids
        assert ocupado.id not in ids
        assert total == 1

    def test_excluye_el_propio_servicio_destino(
        self, db_session, make_servicio, vehiculo
    ):
        # Un vehículo ya asignado al PROPIO destino sigue siendo "disponible"
        # para él (se excluye del cálculo de solape): permite reabrir el picker.
        destino = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=vehiculo.id, servicio_id=destino.id
        )
        items, _ = service.listar_vehiculos_disponibles_para_servicio(
            db_session, servicio_id=destino.id
        )
        assert vehiculo.id in {v.id for v in items}

    def test_averiado_no_aparece(
        self, db_session, make_servicio, make_vehiculo
    ):
        from app.models.material import EstadoInventario

        operativo = make_vehiculo(codigo_interno="VH-OK")
        make_vehiculo(
            codigo_interno="VH-KO", estado=EstadoInventario.AVERIADO
        )
        destino = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.BORRADOR,
        )
        items, total = service.listar_vehiculos_disponibles_para_servicio(
            db_session, servicio_id=destino.id
        )
        assert {v.id for v in items} == {operativo.id}
        assert total == 1

    def test_fecha_fin_null_no_filtra_por_solape(
        self, db_session, make_servicio, make_vehiculo
    ):
        # El bloqueante ocupa 09-14, pero el destino tiene fin abierto: no se
        # evalúa solape, así que el vehículo sigue apareciendo (Política A r.2).
        ocupado = make_vehiculo(codigo_interno="VH-OCU")
        bloqueante = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=ocupado.id, servicio_id=bloqueante.id
        )
        destino = _servicio(
            make_servicio, inicio=A_INI, fin=None,
            estado=EstadoServicio.BORRADOR,
        )
        items, _ = service.listar_vehiculos_disponibles_para_servicio(
            db_session, servicio_id=destino.id
        )
        assert ocupado.id in {v.id for v in items}

    def test_servicio_inexistente_404(self, db_session):
        with pytest.raises(service.ServicioNoEncontrado):
            service.listar_vehiculos_disponibles_para_servicio(
                db_session, servicio_id=uuid.uuid4()
            )


class TestServicioMaterialesDisponibles:
    def test_material_sin_stock_libre_no_aparece_y_con_stock_si(
        self, db_session, make_servicio, make_material
    ):
        # `agotado`: 2 unidades, ambas reservadas por un servicio solapante.
        # `con_stock`: 2 unidades, ninguna reservada.
        agotado = make_material(
            nombre="Conos", tipo=TipoMaterial.SERVICIO, cantidad=2
        )
        con_stock = make_material(
            nombre="Vallas", tipo=TipoMaterial.SERVICIO, cantidad=2
        )
        bloqueante = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_material_a_servicio(
            db_session, material_id=agotado.id, servicio_id=bloqueante.id,
            cantidad=2,
        )
        # Destino: 12-16, solapa con el bloqueante (09-14).
        destino = _servicio(
            make_servicio,
            inicio=datetime(2026, 6, 1, 12, 0),
            fin=datetime(2026, 6, 1, 16, 0),
            estado=EstadoServicio.BORRADOR,
        )
        items, total = service.listar_materiales_disponibles_para_servicio(
            db_session, servicio_id=destino.id
        )
        ids = {m.id for m in items}
        assert con_stock.id in ids
        assert agotado.id not in ids
        assert total == 1

    def test_solape_parcial_deja_una_unidad_libre_y_aparece(
        self, db_session, make_servicio, make_material
    ):
        # 2 unidades, 1 reservada por solapante → queda 1 libre → aparece
        # (el picker pide una sola unidad).
        m = make_material(tipo=TipoMaterial.SERVICIO, cantidad=2)
        bloqueante = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_material_a_servicio(
            db_session, material_id=m.id, servicio_id=bloqueante.id, cantidad=1
        )
        destino = _servicio(
            make_servicio,
            inicio=datetime(2026, 6, 1, 12, 0),
            fin=datetime(2026, 6, 1, 16, 0),
            estado=EstadoServicio.BORRADOR,
        )
        items, _ = service.listar_materiales_disponibles_para_servicio(
            db_session, servicio_id=destino.id
        )
        assert m.id in {mat.id for mat in items}

    def test_perdido_no_aparece(
        self, db_session, make_servicio, make_material
    ):
        from app.models.material import EstadoInventario

        operativo = make_material(tipo=TipoMaterial.SERVICIO, cantidad=1)
        make_material(
            tipo=TipoMaterial.SERVICIO,
            cantidad=1,
            estado=EstadoInventario.PERDIDO,
        )
        destino = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.BORRADOR,
        )
        items, total = service.listar_materiales_disponibles_para_servicio(
            db_session, servicio_id=destino.id
        )
        assert {m.id for m in items} == {operativo.id}
        assert total == 1

    def test_stock_consumido_fuera_de_servicio_no_aparece(
        self, db_session, make_servicio, make_material, voluntario
    ):
        # Una sola unidad PRESTABLE, prestada a un voluntario (global, sin
        # intervalo): no queda nada libre para ningún servicio.
        m = make_material(tipo=TipoMaterial.PRESTABLE, cantidad=1)
        service.asignar_material_a_voluntario(
            db_session,
            material_id=m.id,
            voluntario_id=voluntario.id,
            tipo=TipoAsignacion.PRESTAMO,
        )
        destino = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.BORRADOR,
        )
        items, _ = service.listar_materiales_disponibles_para_servicio(
            db_session, servicio_id=destino.id
        )
        assert m.id not in {mat.id for mat in items}

    def test_servicio_inexistente_404(self, db_session):
        with pytest.raises(service.ServicioNoEncontrado):
            service.listar_materiales_disponibles_para_servicio(
                db_session, servicio_id=uuid.uuid4()
            )


class TestEndpointDisponibleParaServicio:
    BASE = "/api/v1/inventario"

    def test_vehiculo_filtra_por_disponibilidad(
        self, jefe_client, db_session, make_servicio, make_vehiculo
    ):
        ocupado = make_vehiculo(codigo_interno="VH-OCU")
        libre = make_vehiculo(codigo_interno="VH-LIB")
        bloqueante = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_vehiculo_a_servicio(
            db_session, vehiculo_id=ocupado.id, servicio_id=bloqueante.id
        )
        destino = _servicio(
            make_servicio,
            inicio=datetime(2026, 6, 1, 12, 0),
            fin=datetime(2026, 6, 1, 16, 0),
            estado=EstadoServicio.BORRADOR,
        )
        r = jefe_client.get(
            f"{self.BASE}/vehiculos",
            params={"disponible_para_servicio": str(destino.id)},
        )
        assert r.status_code == 200
        ids = {v["id"] for v in r.json()}
        assert str(libre.id) in ids
        assert str(ocupado.id) not in ids
        assert r.headers["X-Total-Count"] == "1"

    def test_material_filtra_por_disponibilidad(
        self, jefe_client, db_session, make_servicio, make_material
    ):
        agotado = make_material(
            nombre="Conos", tipo=TipoMaterial.SERVICIO, cantidad=2
        )
        con_stock = make_material(
            nombre="Vallas", tipo=TipoMaterial.SERVICIO, cantidad=2
        )
        bloqueante = _servicio(
            make_servicio, inicio=A_INI, fin=A_FIN,
            estado=EstadoServicio.PUBLICADO,
        )
        service.asignar_material_a_servicio(
            db_session, material_id=agotado.id, servicio_id=bloqueante.id,
            cantidad=2,
        )
        destino = _servicio(
            make_servicio,
            inicio=datetime(2026, 6, 1, 12, 0),
            fin=datetime(2026, 6, 1, 16, 0),
            estado=EstadoServicio.BORRADOR,
        )
        r = jefe_client.get(
            f"{self.BASE}/material",
            params={"disponible_para_servicio": str(destino.id)},
        )
        assert r.status_code == 200
        ids = {m["id"] for m in r.json()}
        assert str(con_stock.id) in ids
        assert str(agotado.id) not in ids
        assert r.headers["X-Total-Count"] == "1"

    def test_servicio_inexistente_es_404(self, jefe_client):
        r = jefe_client.get(
            f"{self.BASE}/vehiculos",
            params={"disponible_para_servicio": str(uuid.uuid4())},
        )
        assert r.status_code == 404

    def test_sin_param_mantiene_listado_normal(
        self, jefe_client, make_vehiculo
    ):
        from app.models.material import EstadoInventario

        make_vehiculo(codigo_interno="VH-OK")
        make_vehiculo(
            codigo_interno="VH-KO", estado=EstadoInventario.AVERIADO
        )
        # Sin el query param el listado normal NO filtra por estado: salen los 2.
        r = jefe_client.get(f"{self.BASE}/vehiculos")
        assert r.status_code == 200
        assert r.headers["X-Total-Count"] == "2"


# ---------------------------------------------------------------------------
# Migración del índice (PR6)
# ---------------------------------------------------------------------------


import os  # noqa: E402

import sqlalchemy as sa  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://custodiam:test@localhost:5433/custodiam_test",
)

REV_PR6 = "c4d5e6f7a8b9"
REV_ANTES_PR6 = "b2c3d4e5f6a1"
INDEX_NAME = "ix_servicios_fecha_inicio_fecha_fin"


@pytest.fixture
def throwaway_db_url_pr6():
    base, _, _ = TEST_DATABASE_URL.rpartition("/")
    db_name = f"custodiam_pr6_{uuid.uuid4().hex[:10]}"
    admin_url = f"{base}/postgres"

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin_engine.dispose()

    yield f"{base}/{db_name}"

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :db AND pid <> pg_backend_pid()"
            ),
            {"db": db_name},
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
    admin_engine.dispose()


def test_migracion_indice_pr6(throwaway_db_url_pr6, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", throwaway_db_url_pr6)
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", throwaway_db_url_pr6)

    command.upgrade(cfg, "head")

    engine = create_engine(throwaway_db_url_pr6)
    insp = sa.inspect(engine)
    indexes = {i["name"] for i in insp.get_indexes("servicios")}
    assert INDEX_NAME in indexes
    engine.dispose()

    command.downgrade(cfg, REV_ANTES_PR6)

    engine = create_engine(throwaway_db_url_pr6)
    insp = sa.inspect(engine)
    indexes = {i["name"] for i in insp.get_indexes("servicios")}
    assert INDEX_NAME not in indexes
    engine.dispose()
