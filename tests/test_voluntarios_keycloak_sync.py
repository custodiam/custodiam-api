"""Tests de la sincronización Keycloak ↔ BD en el router de voluntarios
(EN-02-03).

Los tests del router básico (`test_voluntarios_router.py`) ya prueban
las respuestas HTTP de alta y baja. Aquí nos centramos en los efectos
laterales en el `FakeKeycloakAdmin`: qué se llamó, con qué argumentos
y cómo se comporta el endpoint cuando el cliente devuelve un error.
"""

from __future__ import annotations

from app.services.keycloak_admin import get_keycloak_admin

BASE = "/api/v1/voluntarios"


# ---------------------------------------------------------------------------
# POST /voluntarios
# ---------------------------------------------------------------------------


class TestAltaCreaUsuarioEnKeycloak:
    def test_alta_invoca_crear_usuario_con_datos_del_request(
        self, admin_client, fake_keycloak_admin
    ):
        r = admin_client.post(
            BASE,
            json={
                "nombre": "Ana García",
                "telefono": "+34611111111",
                "municipio": "Zaragoza",
                "fecha_nacimiento": "1995-05-15",
                "dni": "12345678Z",
                "email": "ana@example.com",
            },
        )
        assert r.status_code == 201
        assert len(fake_keycloak_admin.usuarios_creados) == 1
        call = fake_keycloak_admin.usuarios_creados[0]
        assert call["username"] == "12345678z"  # DNI tiene prioridad como username
        assert call["email"] == "ana@example.com"
        assert call["given_name"] == "Ana"
        assert call["family_name"] == "García"

    def test_alta_persiste_keycloak_id_devuelto_por_el_cliente(
        self, admin_client, fake_keycloak_admin
    ):
        r = admin_client.post(
            BASE,
            json={
                "nombre": "Beatriz López",
                "telefono": "+34622222222",
                "municipio": "Zaragoza",
                "fecha_nacimiento": "1990-01-01",
                "email": "beatriz@example.com",
            },
        )
        assert r.status_code == 201
        # El FakeKeycloakAdmin asigna kc-fake-NNNN secuencialmente.
        assert r.json()["keycloak_id"].startswith("kc-fake-")

    def test_alta_username_fallback_email_si_no_hay_dni(
        self, admin_client, fake_keycloak_admin
    ):
        r = admin_client.post(
            BASE,
            json={
                "nombre": "Carlos Ruiz",
                "telefono": "+34633333333",
                "municipio": "Madrid",
                "fecha_nacimiento": "1985-01-01",
                "email": "carlos@example.com",
            },
        )
        assert r.status_code == 201
        assert fake_keycloak_admin.usuarios_creados[0]["username"] == "carlos@example.com"

    def test_alta_con_keycloak_caido_devuelve_502_y_no_crea_en_bd(
        self, admin_client, db_session
    ):
        from app.main import app
        from tests.conftest import FakeKeycloakAdmin

        # Sustituimos el cliente por uno que falla en `crear`.
        app.dependency_overrides[get_keycloak_admin] = (
            lambda: FakeKeycloakAdmin(fail_on={"crear"})
        )
        try:
            r = admin_client.post(
                BASE,
                json={
                    "nombre": "Diana Falla",
                    "telefono": "+34644444444",
                    "municipio": "Zaragoza",
                    "fecha_nacimiento": "1990-01-01",
                    "dni": "99999999X",
                    "email": "diana.falla@example.com",
                },
            )
            assert r.status_code == 502
            # Tampoco se guardó en BD: la próxima alta con el mismo DNI
            # debería NO devolver 409.
            app.dependency_overrides[get_keycloak_admin] = (
                lambda: FakeKeycloakAdmin()
            )
            r2 = admin_client.post(
                BASE,
                json={
                    "nombre": "Diana Falla",
                    "telefono": "+34644444444",
                    "municipio": "Zaragoza",
                    "fecha_nacimiento": "1990-01-01",
                    "dni": "99999999X",
                    "email": "diana.falla@example.com",
                },
            )
            assert r2.status_code == 201
        finally:
            app.dependency_overrides.pop(get_keycloak_admin, None)

    def test_alta_no_llama_a_keycloak_si_dni_ya_existe(
        self, admin_client, fake_keycloak_admin, make_voluntario
    ):
        # DNI ocupado → 409 sin tocar Keycloak (ahorro de llamadas).
        make_voluntario(dni="44444444X")
        r = admin_client.post(
            BASE,
            json={
                "nombre": "Repetida",
                "telefono": "+34655555555",
                "municipio": "Zaragoza",
                "fecha_nacimiento": "1990-01-01",
                "dni": "44444444X",
                "email": "repetida@example.com",
            },
        )
        assert r.status_code == 409
        assert fake_keycloak_admin.usuarios_creados == []


class TestAltaOnboarding:
    """El alta asigna el rol inicial en Keycloak y envía la invitación."""

    def _alta(self, client):
        return client.post(
            BASE,
            json={
                "nombre": "Nora Onboarding",
                "telefono": "+34666000111",
                "municipio": "Zaragoza",
                "fecha_nacimiento": "1992-03-03",
                "email": "nora@example.com",
            },
        )

    def test_alta_asigna_rol_inicial_voluntario_practicas(
        self, admin_client, fake_keycloak_admin
    ):
        r = self._alta(admin_client)
        assert r.status_code == 201
        kc_id = r.json()["keycloak_id"]
        assert (kc_id, "voluntario_practicas") in fake_keycloak_admin.roles_asignados

    def test_alta_dispara_email_de_invitacion(
        self, admin_client, fake_keycloak_admin
    ):
        r = self._alta(admin_client)
        assert r.status_code == 201
        kc_id = r.json()["keycloak_id"]
        assert len(fake_keycloak_admin.emails_enviados) == 1
        assert fake_keycloak_admin.emails_enviados[0]["keycloak_id"] == kc_id

    def test_alta_con_fallo_de_rol_es_502_y_compensa_desactivando(self, admin_client):
        from app.main import app
        from tests.conftest import FakeKeycloakAdmin

        fake = FakeKeycloakAdmin(fail_on={"rol"})
        app.dependency_overrides[get_keycloak_admin] = lambda: fake
        try:
            r = self._alta(admin_client)
            assert r.status_code == 502
            # Rol bloqueante: se compensa desactivando el usuario recién creado.
            assert len(fake.usuarios_creados) == 1
            assert fake.usuarios_desactivados == [fake.usuarios_creados[0]["id"]]
        finally:
            app.dependency_overrides.pop(get_keycloak_admin, None)

    def test_alta_con_fallo_de_rol_no_crea_en_bd(self, admin_client):
        from app.main import app
        from tests.conftest import FakeKeycloakAdmin

        app.dependency_overrides[get_keycloak_admin] = lambda: FakeKeycloakAdmin(
            fail_on={"rol"}
        )
        try:
            assert self._alta(admin_client).status_code == 502
            # Nada en BD: el reintento sin fallo (mismo email) crea sin 409.
            app.dependency_overrides[get_keycloak_admin] = lambda: FakeKeycloakAdmin()
            assert self._alta(admin_client).status_code == 201
        finally:
            app.dependency_overrides.pop(get_keycloak_admin, None)

    def test_alta_con_fallo_de_email_no_revierte_el_alta(self, admin_client):
        from app.main import app
        from tests.conftest import FakeKeycloakAdmin

        fake = FakeKeycloakAdmin(fail_on={"email"})
        app.dependency_overrides[get_keycloak_admin] = lambda: fake
        try:
            r = self._alta(admin_client)
            # El email es best-effort: el alta NO se revierte si falla.
            assert r.status_code == 201
            kc_id = r.json()["keycloak_id"]
            assert (kc_id, "voluntario_practicas") in fake.roles_asignados
            assert fake.emails_enviados == []
        finally:
            app.dependency_overrides.pop(get_keycloak_admin, None)


# ---------------------------------------------------------------------------
# DELETE /voluntarios/{id}  (soft delete + desactivar en KC)
# ---------------------------------------------------------------------------


class TestBajaDesactivaUsuarioEnKeycloak:
    def test_baja_con_keycloak_id_dispara_desactivar(
        self, admin_client, fake_keycloak_admin, make_voluntario
    ):
        v = make_voluntario(keycloak_id="kc-existing-001")
        r = admin_client.delete(f"{BASE}/{v.id}")
        assert r.status_code == 200
        assert fake_keycloak_admin.usuarios_desactivados == ["kc-existing-001"]

    def test_baja_sin_keycloak_id_no_dispara_llamada(
        self, admin_client, fake_keycloak_admin, make_voluntario
    ):
        # Voluntario heredado sin sync KC (caso real durante la transición).
        v = make_voluntario(keycloak_id=None)
        r = admin_client.delete(f"{BASE}/{v.id}")
        assert r.status_code == 200
        assert fake_keycloak_admin.usuarios_desactivados == []

    def test_baja_con_keycloak_caido_devuelve_502_pero_bd_ya_marcada(
        self, admin_client, db_session, make_voluntario
    ):
        from app.main import app
        from app.models.voluntario import EstadoVoluntario
        from tests.conftest import FakeKeycloakAdmin

        v = make_voluntario(keycloak_id="kc-rompera")
        app.dependency_overrides[get_keycloak_admin] = (
            lambda: FakeKeycloakAdmin(fail_on={"desactivar"})
        )
        try:
            r = admin_client.delete(f"{BASE}/{v.id}")
            assert r.status_code == 502
        finally:
            app.dependency_overrides.pop(get_keycloak_admin, None)

        # La BD ya quedó marcada baja (decisión: no rollback porque la
        # parte importante para el operador es marcar la baja en BD;
        # la desactivación en KC se puede reintentar manualmente).
        db_session.expire_all()
        from app.repositories import voluntarios as repo

        actual = repo.get(db_session, v.id)
        assert actual is not None
        assert actual.estado == EstadoVoluntario.BAJA


# ---------------------------------------------------------------------------
# POST /voluntarios/{id}/anonimizar (RGPD + desactivar en KC)
# ---------------------------------------------------------------------------


class TestAnonimizarDesactivaUsuarioEnKeycloak:
    def test_anonimizar_dispara_desactivar_con_id_capturado_antes(
        self, admin_client, fake_keycloak_admin, make_voluntario
    ):
        v = make_voluntario(keycloak_id="kc-rgpd-001")
        r = admin_client.post(f"{BASE}/{v.id}/anonimizar")
        assert r.status_code == 200
        assert fake_keycloak_admin.usuarios_desactivados == ["kc-rgpd-001"]
        assert r.json()["keycloak_id"] is None

    def test_anonimizar_sin_keycloak_id_no_dispara_llamada(
        self, admin_client, fake_keycloak_admin, make_voluntario
    ):
        v = make_voluntario(keycloak_id=None)
        r = admin_client.post(f"{BASE}/{v.id}/anonimizar")
        assert r.status_code == 200
        assert fake_keycloak_admin.usuarios_desactivados == []
