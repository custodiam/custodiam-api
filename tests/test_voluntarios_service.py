"""Tests del Service de voluntarios (EN-02-02).

Cubren reglas de negocio y excepciones de dominio sin tocar la capa
HTTP. La verificación de respuestas y de RBAC declarativo vive en
`test_voluntarios_router.py`.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.models.voluntario import EstadoVoluntario
from app.schemas.voluntario import (
    VoluntarioCreate,
    VoluntarioUpdateAdmin,
    VoluntarioUpdateSelf,
)
from app.services import voluntarios as service

# ---------------------------------------------------------------------------
# Crear
# ---------------------------------------------------------------------------


class TestCrear:
    def _payload(self, **overrides):
        base = dict(
            nombre="Nueva Voluntaria",
            telefono="+34666123456",
            municipio="Zaragoza",
            fecha_nacimiento=date(1995, 1, 15),
        )
        base.update(overrides)
        # Email obligatorio en el alta; derivado del nombre para que dos
        # payloads con nombres distintos no choquen con el UNIQUE de email.
        base.setdefault(
            "email", f"{base['nombre'].replace(' ', '.').lower()}@example.com"
        )
        return VoluntarioCreate(**base)

    def test_crear_persiste_voluntario_activo_con_fecha_alta_inyectada(self, db_session):
        v = service.crear(
            db_session,
            data=self._payload(),
            fecha_alta=date(2026, 5, 27),
            keycloak_id="kc-abc-123",
        )
        assert v.id is not None
        assert v.estado == EstadoVoluntario.ACTIVO
        assert v.fecha_alta == date(2026, 5, 27)
        assert v.keycloak_id == "kc-abc-123"

    def test_crear_con_fecha_alta_default_today(self, db_session):
        v = service.crear(db_session, data=self._payload())
        assert v.fecha_alta == date.today()

    def test_crear_falla_con_dni_duplicado(self, db_session, make_voluntario):
        make_voluntario(dni="55555555E")
        with pytest.raises(service.DniDuplicado):
            service.crear(db_session, data=self._payload(dni="55555555E"))

    def test_crear_falla_con_email_duplicado(self, db_session, make_voluntario):
        make_voluntario(email="repe@example.com")
        with pytest.raises(service.EmailDuplicado):
            service.crear(db_session, data=self._payload(email="repe@example.com"))

    def test_crear_permite_dos_voluntarios_sin_dni(self, db_session):
        # Dos voluntarios con dni=None coexisten (UNIQUE no aplica a NULL).
        service.crear(db_session, data=self._payload())
        v2 = service.crear(db_session, data=self._payload(nombre="Otro"))
        assert v2.dni is None


# ---------------------------------------------------------------------------
# Actualizar (admin + self)
# ---------------------------------------------------------------------------


class TestActualizarAdmin:
    def test_actualizar_campos_arbitrarios(self, db_session, voluntario):
        actualizado = service.actualizar_admin(
            db_session,
            voluntario.id,
            VoluntarioUpdateAdmin(municipio="Huesca", conductor_habilitado=True),
        )
        assert actualizado.municipio == "Huesca"
        assert actualizado.conductor_habilitado is True

    def test_actualizar_voluntario_inexistente_lanza_404(self, db_session):
        with pytest.raises(service.VoluntarioNoEncontrado):
            service.actualizar_admin(
                db_session,
                uuid.uuid4(),
                VoluntarioUpdateAdmin(municipio="Huesca"),
            )

    def test_actualizar_dni_a_uno_ya_existente_falla(
        self, db_session, make_voluntario
    ):
        make_voluntario(dni="66666666F")
        otro = make_voluntario()
        with pytest.raises(service.DniDuplicado):
            service.actualizar_admin(
                db_session,
                otro.id,
                VoluntarioUpdateAdmin(dni="66666666F"),
            )

    def test_actualizar_dni_al_propio_es_idempotente(
        self, db_session, make_voluntario
    ):
        v = make_voluntario(dni="77777777G")
        actualizado = service.actualizar_admin(
            db_session, v.id, VoluntarioUpdateAdmin(dni="77777777G")
        )
        assert actualizado.dni == "77777777G"

    def test_actualizar_no_toca_campos_no_enviados(
        self, db_session, make_voluntario
    ):
        v = make_voluntario(nombre="Original", municipio="Zaragoza")
        actualizado = service.actualizar_admin(
            db_session, v.id, VoluntarioUpdateAdmin(municipio="Huesca")
        )
        assert actualizado.nombre == "Original"


class TestActualizarPropio:
    def test_actualizar_solo_campos_de_contacto(
        self, db_session, make_voluntario
    ):
        make_voluntario(keycloak_id="kc-self-1", telefono="+34611111111")
        actualizado = service.actualizar_propio(
            db_session,
            "kc-self-1",
            VoluntarioUpdateSelf(telefono="+34622222222"),
        )
        assert actualizado.telefono == "+34622222222"

    def test_actualizar_propio_sin_voluntario_en_bd_lanza_404(self, db_session):
        with pytest.raises(service.VoluntarioNoEncontrado):
            service.actualizar_propio(
                db_session,
                "kc-fantasma",
                VoluntarioUpdateSelf(telefono="+34600000000"),
            )

    def test_actualizar_propio_email_a_uno_existente_falla(
        self, db_session, make_voluntario
    ):
        make_voluntario(email="ocupado@example.com")
        make_voluntario(keycloak_id="kc-self-2", email="mio@example.com")
        with pytest.raises(service.EmailDuplicado):
            service.actualizar_propio(
                db_session,
                "kc-self-2",
                VoluntarioUpdateSelf(email="ocupado@example.com"),
            )


# ---------------------------------------------------------------------------
# Dar de baja
# ---------------------------------------------------------------------------


class TestDarBaja:
    def test_baja_marca_estado_y_pone_fecha(self, db_session, voluntario):
        baja = service.dar_baja(
            db_session, voluntario.id, fecha_baja=date(2026, 6, 1)
        )
        assert baja.estado == EstadoVoluntario.BAJA
        assert baja.fecha_baja == date(2026, 6, 1)

    def test_baja_sin_fecha_default_hoy(self, db_session, voluntario):
        baja = service.dar_baja(db_session, voluntario.id)
        assert baja.fecha_baja == date.today()

    def test_baja_voluntario_inexistente_lanza_404(self, db_session):
        with pytest.raises(service.VoluntarioNoEncontrado):
            service.dar_baja(db_session, uuid.uuid4())


# ---------------------------------------------------------------------------
# Anonimizar (Art. 17 RGPD)
# ---------------------------------------------------------------------------


class TestAnonimizar:
    def test_anonimizar_genera_placeholder_secuencial(
        self, db_session, make_voluntario
    ):
        v1 = make_voluntario(nombre="Primera")
        v2 = make_voluntario(nombre="Segunda")
        a1 = service.anonimizar(db_session, v1.id)
        a2 = service.anonimizar(db_session, v2.id)
        assert a1.nombre == "Voluntario anonimizado #1"
        assert a2.nombre == "Voluntario anonimizado #2"

    def test_anonimizar_borra_pii_y_fuerza_baja(self, db_session, make_voluntario):
        v = make_voluntario(
            dni="88888888H",
            email="diana@example.com",
            keycloak_id="kc-d",
        )
        anonimizado = service.anonimizar(db_session, v.id)
        assert anonimizado.dni is None
        assert anonimizado.email is None
        assert anonimizado.keycloak_id is None
        assert anonimizado.estado == EstadoVoluntario.BAJA

    def test_anonimizar_inexistente_lanza_404(self, db_session):
        with pytest.raises(service.VoluntarioNoEncontrado):
            service.anonimizar(db_session, uuid.uuid4())


# ---------------------------------------------------------------------------
# Lecturas
# ---------------------------------------------------------------------------


class TestObtener:
    def test_obtener_carga_voluntario_con_relaciones(
        self, db_session, voluntario
    ):
        v = service.obtener(db_session, voluntario.id)
        assert v.id == voluntario.id
        # Las relaciones vacías deben ser listas vacías, no None.
        assert v.acreditaciones == []
        assert v.tallas == []
        assert v.contactos_emergencia == []

    def test_obtener_inexistente_lanza_404(self, db_session):
        with pytest.raises(service.VoluntarioNoEncontrado):
            service.obtener(db_session, uuid.uuid4())


class TestObtenerPropio:
    def test_obtener_propio_localiza_por_keycloak_id(
        self, db_session, make_voluntario
    ):
        v = make_voluntario(keycloak_id="kc-me")
        propio = service.obtener_propio(db_session, "kc-me")
        assert propio.id == v.id

    def test_obtener_propio_sin_bd_lanza_404(self, db_session):
        with pytest.raises(service.VoluntarioNoEncontrado):
            service.obtener_propio(db_session, "kc-nadie")


class TestListar:
    def test_listar_devuelve_items_y_total(self, db_session, make_voluntario):
        make_voluntario(nombre="Ana")
        make_voluntario(nombre="Bea")
        items, total = service.listar(db_session)
        assert total == 2
        assert len(items) == 2
