"""Tests del Repository de voluntarios (EN-02-02).

Verifican queries SQLModel contra Postgres real. No tocan la capa HTTP
ni el sistema RBAC. La cobertura RBAC vive en `test_voluntarios_router.py`
y la lógica de negocio compleja en `test_voluntarios_service.py`.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.models.voluntario import EstadoVoluntario, Voluntario
from app.models.voluntario_rol import VoluntarioRol
from app.repositories import voluntarios as repo


def test_get_devuelve_none_si_no_existe(db_session):
    assert repo.get(db_session, uuid.uuid4()) is None


def test_get_devuelve_el_voluntario_si_existe(db_session, voluntario):
    encontrado = repo.get(db_session, voluntario.id)
    assert encontrado is not None
    assert encontrado.id == voluntario.id


def test_get_full_carga_relaciones_nested(db_session, make_voluntario):
    """`get_full` debe traer acreditaciones/tallas/contactos en la misma query.

    El test no comprueba el número de queries SQL exactas (frágil con
    SQLAlchemy 2.x) pero sí que se puedan iterar las relaciones sin
    `DetachedInstanceError`.
    """

    v = make_voluntario()
    full = repo.get_full(db_session, v.id)
    assert full is not None
    assert isinstance(full.acreditaciones, list)
    assert isinstance(full.tallas, list)
    assert isinstance(full.contactos_emergencia, list)
    assert isinstance(full.roles, list)


def test_get_by_keycloak_id_localiza_por_sub(db_session, make_voluntario):
    v = make_voluntario(keycloak_id="kc-sub-123")
    encontrado = repo.get_by_keycloak_id(db_session, "kc-sub-123")
    assert encontrado is not None
    assert encontrado.id == v.id


def test_get_by_keycloak_id_devuelve_none_si_no_coincide(db_session):
    assert repo.get_by_keycloak_id(db_session, "no-existe") is None


def test_exists_with_dni_true_si_lo_hay(db_session, make_voluntario):
    make_voluntario(dni="12345678Z")
    assert repo.exists_with_dni(db_session, "12345678Z") is True


def test_exists_with_dni_false_si_no_lo_hay(db_session):
    assert repo.exists_with_dni(db_session, "00000000X") is False


def test_exists_with_dni_excluye_id_para_patch(db_session, make_voluntario):
    """Permitir conservar el propio DNI en un PATCH del mismo voluntario."""

    v = make_voluntario(dni="11111111H")
    assert repo.exists_with_dni(db_session, "11111111H") is True
    assert repo.exists_with_dni(db_session, "11111111H", exclude_id=v.id) is False


def test_exists_with_email_excluye_id(db_session, make_voluntario):
    v = make_voluntario(email="ana@example.com")
    assert repo.exists_with_email(db_session, "ana@example.com") is True
    assert (
        repo.exists_with_email(db_session, "ana@example.com", exclude_id=v.id) is False
    )


class TestListPaginated:
    """Lista paginada con filtros opcionales (CU-15 / US-02-09)."""

    @pytest.fixture
    def trio_voluntarios(self, make_voluntario):
        return [
            make_voluntario(nombre="Ana García", dni="11111111A"),
            make_voluntario(nombre="Beatriz López", dni="22222222B"),
            make_voluntario(
                nombre="Carlos Pérez",
                dni="33333333C",
                fecha_alta=date(2026, 2, 1),
            ),
        ]

    def test_lista_vacia_si_no_hay_voluntarios(self, db_session):
        items, total = repo.list_paginated(db_session)
        assert items == []
        assert total == 0

    def test_lista_devuelve_total_y_items(self, db_session, trio_voluntarios):
        items, total = repo.list_paginated(db_session)
        assert total == 3
        assert len(items) == 3

    def test_lista_ordenada_por_nombre_ascendente(self, db_session, trio_voluntarios):
        items, _ = repo.list_paginated(db_session)
        assert [v.nombre for v in items] == ["Ana García", "Beatriz López", "Carlos Pérez"]

    def test_paginacion_skip_limit(self, db_session, trio_voluntarios):
        page1, total = repo.list_paginated(db_session, skip=0, limit=2)
        page2, _ = repo.list_paginated(db_session, skip=2, limit=2)
        assert total == 3
        assert len(page1) == 2
        assert len(page2) == 1
        assert page1[0].nombre == "Ana García"
        assert page2[0].nombre == "Carlos Pérez"

    def test_filtro_estado_solo_activos(self, db_session, trio_voluntarios):
        # Damos de baja a Beatriz.
        beatriz = trio_voluntarios[1]
        repo.soft_delete(db_session, beatriz, fecha_baja=date.today())

        activos, total = repo.list_paginated(
            db_session, estado=EstadoVoluntario.ACTIVO
        )
        assert total == 2
        assert beatriz.id not in {v.id for v in activos}

    def test_filtro_q_busca_por_nombre_case_insensitive(
        self, db_session, trio_voluntarios
    ):
        items, total = repo.list_paginated(db_session, q="ana")
        assert total == 1
        assert items[0].nombre == "Ana García"

    def test_filtro_q_busca_tambien_por_dni(self, db_session, trio_voluntarios):
        items, total = repo.list_paginated(db_session, q="33333333")
        assert total == 1
        assert items[0].nombre == "Carlos Pérez"

    def test_filtro_q_busca_tambien_por_telefono(self, db_session, make_voluntario):
        # El teléfono es un identificador habitual en campo; q debe alcanzarlo.
        make_voluntario(nombre="Ana García", telefono="600111222")
        make_voluntario(nombre="Otro Voluntario", telefono="699888777")

        items, total = repo.list_paginated(db_session, q="600111")
        assert total == 1
        assert items[0].nombre == "Ana García"

    def test_filtro_q_sin_resultados(self, db_session, trio_voluntarios):
        items, total = repo.list_paginated(db_session, q="Zzz no existe")
        assert items == []
        assert total == 0

    def test_filtro_rol_solo_devuelve_quienes_lo_tienen_activo(
        self, db_session, trio_voluntarios
    ):
        from sqlmodel import select

        from app.models.rol import Rol

        rol_jefe = db_session.exec(
            select(Rol).where(Rol.nombre == "jefe_equipo")
        ).first()
        assert rol_jefe is not None

        # Solo Beatriz es jefe_equipo y con asignación activa.
        beatriz = trio_voluntarios[1]
        db_session.add(
            VoluntarioRol(
                voluntario_id=beatriz.id,
                rol_id=rol_jefe.id,
                fecha_desde=date(2026, 1, 1),
            )
        )
        # Carlos fue jefe_equipo pero ya no (fecha_hasta no nula).
        carlos = trio_voluntarios[2]
        db_session.add(
            VoluntarioRol(
                voluntario_id=carlos.id,
                rol_id=rol_jefe.id,
                fecha_desde=date(2026, 1, 1),
                fecha_hasta=date(2026, 3, 1),
            )
        )
        db_session.commit()

        items, total = repo.list_paginated(db_session, rol_id=rol_jefe.id)
        assert total == 1
        assert items[0].id == beatriz.id


class TestCreate:
    def test_create_con_campos_minimos(self, db_session):
        v = repo.create(
            db_session,
            data=dict(
                nombre="Nuevo Voluntario",
                telefono="+34666000000",
                municipio="Zaragoza",
                fecha_nacimiento=date(1995, 1, 1),
                fecha_alta=date(2026, 1, 1),
            ),
        )
        assert v.id is not None
        assert v.estado == EstadoVoluntario.ACTIVO
        assert v.conductor_habilitado is False

    def test_create_persiste_y_es_recuperable_por_get(self, db_session):
        v = repo.create(
            db_session,
            data=dict(
                nombre="Persistente",
                telefono="+34666111111",
                municipio="Madrid",
                fecha_nacimiento=date(1990, 1, 1),
                fecha_alta=date(2026, 1, 1),
            ),
        )
        recuperado = repo.get(db_session, v.id)
        assert recuperado is not None
        assert recuperado.nombre == "Persistente"


class TestUpdate:
    def test_update_aplica_campos_y_persiste(self, db_session, voluntario):
        actualizado = repo.update(
            db_session, voluntario, data={"municipio": "Huesca"}
        )
        assert actualizado.municipio == "Huesca"
        # Re-fetch desde otra "sesión lógica" no aplica aquí porque el
        # mismo session pool ve el cambio; el commit garantiza que sí
        # se ha persistido.
        recuperado = repo.get(db_session, voluntario.id)
        assert recuperado is not None
        assert recuperado.municipio == "Huesca"

    def test_update_actualiza_solo_campos_pedidos(self, db_session, make_voluntario):
        v = make_voluntario(nombre="Original", telefono="+34600000000")
        repo.update(db_session, v, data={"telefono": "+34611111111"})
        recuperado = repo.get(db_session, v.id)
        assert recuperado is not None
        assert recuperado.nombre == "Original"
        assert recuperado.telefono == "+34611111111"


class TestSoftDelete:
    def test_soft_delete_pone_estado_baja_y_fecha(self, db_session, voluntario):
        repo.soft_delete(db_session, voluntario, fecha_baja=date(2026, 6, 1))
        recuperado = repo.get(db_session, voluntario.id)
        assert recuperado is not None
        assert recuperado.estado == EstadoVoluntario.BAJA
        assert recuperado.fecha_baja == date(2026, 6, 1)

    def test_soft_delete_no_borra_la_fila(self, db_session, voluntario):
        repo.soft_delete(db_session, voluntario, fecha_baja=date.today())
        assert db_session.get(Voluntario, voluntario.id) is not None

    def test_soft_delete_mantiene_keycloak_id_para_revertir(
        self, db_session, make_voluntario
    ):
        v = make_voluntario(keycloak_id="kc-baja-1")
        repo.soft_delete(db_session, v, fecha_baja=date.today())
        recuperado = repo.get(db_session, v.id)
        assert recuperado is not None
        assert recuperado.keycloak_id == "kc-baja-1"


class TestAnonimizar:
    def test_anonimizar_sustituye_nombre_y_borra_datos_personales(
        self, db_session, make_voluntario
    ):
        v = make_voluntario(
            nombre="Diana Real",
            dni="44444444D",
            email="diana@example.com",
            foto_url="https://example.com/foto.jpg",
            direccion="Calle Falsa 123",
            keycloak_id="kc-diana",
        )
        repo.anonimizar(
            db_session, v, placeholder_nombre="Voluntario anonimizado #1"
        )
        recuperado = repo.get(db_session, v.id)
        assert recuperado is not None
        assert recuperado.nombre == "Voluntario anonimizado #1"
        assert recuperado.dni is None
        assert recuperado.email is None
        assert recuperado.foto_url is None
        assert recuperado.direccion is None
        assert recuperado.telefono == "ANONIMIZADO"
        assert recuperado.keycloak_id is None

    def test_anonimizar_fuerza_baja_si_estaba_activo(
        self, db_session, voluntario
    ):
        assert voluntario.estado == EstadoVoluntario.ACTIVO
        repo.anonimizar(db_session, voluntario, placeholder_nombre="X")
        recuperado = repo.get(db_session, voluntario.id)
        assert recuperado is not None
        assert recuperado.estado == EstadoVoluntario.BAJA
        assert recuperado.fecha_baja is not None

    def test_anonimizar_respeta_fecha_baja_existente(
        self, db_session, make_voluntario
    ):
        v = make_voluntario()
        repo.soft_delete(db_session, v, fecha_baja=date(2026, 3, 15))
        repo.anonimizar(db_session, v, placeholder_nombre="X")
        recuperado = repo.get(db_session, v.id)
        assert recuperado is not None
        assert recuperado.fecha_baja == date(2026, 3, 15)


class TestCountAnonimizados:
    def test_count_anonimizados_devuelve_cero_si_no_hay(self, db_session):
        assert repo.count_anonimizados(db_session) == 0

    def test_count_anonimizados_cuenta_los_que_coinciden_con_patron(
        self, db_session, make_voluntario
    ):
        v1 = make_voluntario()
        v2 = make_voluntario()
        repo.anonimizar(db_session, v1, placeholder_nombre="Voluntario anonimizado #1")
        repo.anonimizar(db_session, v2, placeholder_nombre="Voluntario anonimizado #2")
        # Voluntario "normal" no debe contar.
        make_voluntario(nombre="Persona Real")
        assert repo.count_anonimizados(db_session) == 2
