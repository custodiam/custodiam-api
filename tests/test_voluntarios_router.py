"""Tests E2E del router de voluntarios (EN-02-02).

Verifican los códigos HTTP, la forma del payload, los headers de
paginación y la matriz RBAC declarativa. La lógica de negocio en
profundidad se cubre en `test_voluntarios_service.py` y las queries
en `test_voluntarios_repository.py`.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.core.permissions import Permission

BASE = "/api/v1/voluntarios"


# ---------------------------------------------------------------------------
# Anónimo: 401 en todos los endpoints
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", BASE),
        ("get", f"{BASE}/me"),
        ("patch", f"{BASE}/me"),
        ("post", BASE),
        ("get", f"{BASE}/{uuid.uuid4()}"),
        ("patch", f"{BASE}/{uuid.uuid4()}"),
        ("delete", f"{BASE}/{uuid.uuid4()}"),
        ("post", f"{BASE}/{uuid.uuid4()}/anonimizar"),
    ],
)
def test_endpoints_sin_token_devuelven_401(client, method, path):
    request = getattr(client, method)
    response = request(path) if method in {"get", "delete"} else request(path, json={})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /voluntarios
# ---------------------------------------------------------------------------


class TestListar:
    def test_lista_vacia_devuelve_array_y_header_total(self, authenticated_client):
        r = authenticated_client.get(BASE)
        assert r.status_code == 200
        assert r.json() == []
        assert r.headers["X-Total-Count"] == "0"

    def test_lista_con_voluntarios_devuelve_summary(
        self, authenticated_client, make_voluntario
    ):
        make_voluntario(nombre="Ana García")
        make_voluntario(nombre="Beatriz López")
        r = authenticated_client.get(BASE)
        assert r.status_code == 200
        nombres = [v["nombre"] for v in r.json()]
        assert nombres == ["Ana García", "Beatriz López"]
        assert r.headers["X-Total-Count"] == "2"

    def test_filtro_q_funciona(self, authenticated_client, make_voluntario):
        make_voluntario(nombre="Ana García")
        make_voluntario(nombre="Beatriz López")
        r = authenticated_client.get(BASE, params={"q": "beatriz"})
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["nombre"] == "Beatriz López"

    def test_filtro_estado_baja(
        self, admin_client, make_voluntario, db_session
    ):
        from app.repositories import voluntarios as repo

        v = make_voluntario(nombre="Voluntario Baja")
        repo.soft_delete(db_session, v, fecha_baja=date(2026, 6, 1))
        r = admin_client.get(BASE, params={"estado": "baja"})
        assert r.status_code == 200
        assert [v["estado"] for v in r.json()] == ["baja"]

    def test_paginacion_limit(self, authenticated_client, make_voluntario):
        for n in ("Ana", "Bea", "Carlos", "Diana"):
            make_voluntario(nombre=n)
        r = authenticated_client.get(BASE, params={"skip": 1, "limit": 2})
        assert r.status_code == 200
        assert len(r.json()) == 2
        assert r.headers["X-Total-Count"] == "4"
        # skip=1 + orden alfabético → Bea, Carlos
        assert [v["nombre"] for v in r.json()] == ["Bea", "Carlos"]

    def test_paginacion_limit_no_supera_200(self, authenticated_client):
        r = authenticated_client.get(BASE, params={"limit": 999})
        assert r.status_code == 422

    def test_paginacion_skip_negativo_falla(self, authenticated_client):
        r = authenticated_client.get(BASE, params={"skip": -1})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /voluntarios/me y PATCH /voluntarios/me
# ---------------------------------------------------------------------------


class TestSelf:
    def test_get_me_404_si_no_hay_voluntario_vinculado(self, authenticated_client):
        r = authenticated_client.get(f"{BASE}/me")
        assert r.status_code == 404

    def test_get_me_devuelve_ficha_si_kc_id_coincide(
        self, authenticated_client, make_voluntario
    ):
        make_voluntario(keycloak_id="test-user-id", nombre="Yo Mismo")
        r = authenticated_client.get(f"{BASE}/me")
        assert r.status_code == 200
        assert r.json()["nombre"] == "Yo Mismo"

    def test_patch_me_actualiza_telefono(self, authenticated_client, make_voluntario):
        make_voluntario(keycloak_id="test-user-id", telefono="+34611111111")
        r = authenticated_client.patch(
            f"{BASE}/me", json={"telefono": "+34622222222"}
        )
        assert r.status_code == 200
        assert r.json()["telefono"] == "+34622222222"

    def test_patch_me_404_si_kc_id_sin_voluntario(self, authenticated_client):
        r = authenticated_client.patch(f"{BASE}/me", json={"telefono": "+34600000000"})
        assert r.status_code == 404

    def test_patch_me_409_si_email_duplicado(
        self, authenticated_client, make_voluntario
    ):
        make_voluntario(email="ocupado@example.com")
        make_voluntario(keycloak_id="test-user-id", email="mio@example.com")
        r = authenticated_client.patch(
            f"{BASE}/me", json={"email": "ocupado@example.com"}
        )
        assert r.status_code == 409


# ---------------------------------------------------------------------------
# GET /voluntarios/{id}
# ---------------------------------------------------------------------------


class TestObtener:
    def test_obtener_404_si_no_existe(self, jefe_client):
        r = jefe_client.get(f"{BASE}/{uuid.uuid4()}")
        assert r.status_code == 404

    def test_obtener_devuelve_ficha_completa(self, jefe_client, voluntario):
        r = jefe_client.get(f"{BASE}/{voluntario.id}")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == str(voluntario.id)
        assert body["acreditaciones"] == []
        assert body["tallas"] == []
        assert body["contactos_emergencia"] == []

    def test_obtener_como_voluntario_basico_es_403(self, authenticated_client, voluntario):
        # voluntario no tiene voluntarios.ver_ficha (decisión 4 RBAC).
        r = authenticated_client.get(f"{BASE}/{voluntario.id}")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# POST /voluntarios
# ---------------------------------------------------------------------------


class TestCrear:
    def _payload(self, **overrides):
        base = dict(
            nombre="Persona Nueva",
            telefono="+34611111111",
            municipio="Zaragoza",
            fecha_nacimiento="1995-05-15",
        )
        base.update(overrides)
        # Email obligatorio en el alta; derivado del nombre para que dos
        # payloads con nombres distintos no choquen con el UNIQUE de email.
        base.setdefault(
            "email", f"{base['nombre'].replace(' ', '.').lower()}@example.com"
        )
        return base

    def test_alta_como_admin_devuelve_201_y_ficha(self, admin_client):
        r = admin_client.post(BASE, json=self._payload(dni="99999999X"))
        assert r.status_code == 201
        body = r.json()
        assert body["nombre"] == "Persona Nueva"
        assert body["estado"] == "activo"
        assert body["dni"] == "99999999X"

    def test_alta_como_voluntario_es_403(self, authenticated_client):
        r = authenticated_client.post(BASE, json=self._payload())
        assert r.status_code == 403
        assert Permission.VOLUNTARIOS_CREAR.value in r.json()["detail"]

    def test_alta_con_dni_duplicado_es_409(self, admin_client, make_voluntario):
        make_voluntario(dni="00000000A")
        r = admin_client.post(BASE, json=self._payload(dni="00000000A"))
        assert r.status_code == 409

    def test_alta_con_email_duplicado_es_409(
        self, admin_client, make_voluntario
    ):
        make_voluntario(email="repe@example.com")
        r = admin_client.post(BASE, json=self._payload(email="repe@example.com"))
        assert r.status_code == 409

    def test_alta_sin_campos_obligatorios_es_422(self, admin_client):
        r = admin_client.post(BASE, json={"nombre": "Solo Nombre"})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /voluntarios/{id}
# ---------------------------------------------------------------------------


class TestActualizar:
    def test_actualizar_como_admin_devuelve_ficha_modificada(
        self, admin_client, voluntario
    ):
        r = admin_client.patch(
            f"{BASE}/{voluntario.id}", json={"municipio": "Huesca"}
        )
        assert r.status_code == 200
        assert r.json()["municipio"] == "Huesca"

    def test_actualizar_como_voluntario_basico_es_403(
        self, authenticated_client, voluntario
    ):
        r = authenticated_client.patch(
            f"{BASE}/{voluntario.id}", json={"municipio": "Huesca"}
        )
        assert r.status_code == 403

    def test_actualizar_voluntario_inexistente_es_404(self, admin_client):
        r = admin_client.patch(
            f"{BASE}/{uuid.uuid4()}", json={"municipio": "Huesca"}
        )
        assert r.status_code == 404

    def test_actualizar_a_dni_existente_es_409(self, admin_client, make_voluntario):
        make_voluntario(dni="11111111M")
        otro = make_voluntario()
        r = admin_client.patch(f"{BASE}/{otro.id}", json={"dni": "11111111M"})
        assert r.status_code == 409

    def test_actualizar_estado_a_baja(self, admin_client, voluntario):
        r = admin_client.patch(
            f"{BASE}/{voluntario.id}", json={"estado": "suspendido"}
        )
        assert r.status_code == 200
        assert r.json()["estado"] == "suspendido"


# ---------------------------------------------------------------------------
# DELETE /voluntarios/{id} (soft delete)
# ---------------------------------------------------------------------------


class TestDarBaja:
    def test_baja_como_admin_devuelve_ficha_con_estado_baja(
        self, admin_client, voluntario
    ):
        r = admin_client.delete(f"{BASE}/{voluntario.id}")
        assert r.status_code == 200
        body = r.json()
        assert body["estado"] == "baja"
        assert body["fecha_baja"] == date.today().isoformat()

    def test_baja_como_voluntario_basico_es_403(
        self, authenticated_client, voluntario
    ):
        r = authenticated_client.delete(f"{BASE}/{voluntario.id}")
        assert r.status_code == 403

    def test_baja_voluntario_inexistente_es_404(self, admin_client):
        r = admin_client.delete(f"{BASE}/{uuid.uuid4()}")
        assert r.status_code == 404

    def test_baja_mantiene_keycloak_id_y_pii(
        self, admin_client, make_voluntario
    ):
        v = make_voluntario(
            keycloak_id="kc-conservado",
            dni="22222222N",
            email="aun@example.com",
        )
        r = admin_client.delete(f"{BASE}/{v.id}")
        assert r.status_code == 200
        body = r.json()
        assert body["keycloak_id"] == "kc-conservado"
        assert body["dni"] == "22222222N"
        assert body["email"] == "aun@example.com"


# ---------------------------------------------------------------------------
# POST /voluntarios/{id}/anonimizar (Art. 17 RGPD)
# ---------------------------------------------------------------------------


class TestAnonimizar:
    def test_anonimizar_como_coordinador_devuelve_ficha_anonima(
        self, admin_client, make_voluntario
    ):
        v = make_voluntario(
            nombre="Identificable",
            dni="33333333P",
            email="real@example.com",
            keycloak_id="kc-real",
        )
        r = admin_client.post(f"{BASE}/{v.id}/anonimizar")
        assert r.status_code == 200
        body = r.json()
        assert body["nombre"].startswith("Voluntario anonimizado #")
        assert body["dni"] is None
        assert body["email"] is None
        assert body["keycloak_id"] is None
        assert body["estado"] == "baja"

    def test_anonimizar_como_subjefe_es_403(
        self, client_for_role, make_voluntario
    ):
        # subjefe_agrupacion puede dar de baja, pero NO anonimizar
        # (permiso `sistema.exportar_rgpd` restringido).
        v = make_voluntario()
        c = client_for_role(["subjefe_agrupacion"])
        r = c.post(f"{BASE}/{v.id}/anonimizar")
        assert r.status_code == 403

    def test_anonimizar_como_secretario_funciona(
        self, client_for_role, make_voluntario
    ):
        v = make_voluntario()
        c = client_for_role(["secretario"])
        r = c.post(f"{BASE}/{v.id}/anonimizar")
        assert r.status_code == 200

    def test_anonimizar_inexistente_es_404(self, admin_client):
        r = admin_client.post(f"{BASE}/{uuid.uuid4()}/anonimizar")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Matriz RBAC condensada (defensa documental del lockstep front/back)
# ---------------------------------------------------------------------------


class TestMatrizRbacResumida:
    """Verificación cruzada: cada permiso E02 va al rol correcto.

    Estos tests no buscan ser exhaustivos (eso lo hace `test_permissions.py`)
    sino atrapar regresiones en endpoints reales si alguien cambia la
    matriz `ROLE_PERMISSIONS` sin tocar los endpoints en lockstep.
    """

    def test_jefe_equipo_puede_ver_ficha_pero_no_crear(
        self, client_for_role, voluntario
    ):
        c = client_for_role(["jefe_equipo"])
        assert c.get(f"{BASE}/{voluntario.id}").status_code == 200
        assert (
            c.post(
                BASE,
                json={
                    "nombre": "x",
                    "telefono": "+34600000000",
                    "municipio": "x",
                    "fecha_nacimiento": "1995-01-01",
                },
            ).status_code
            == 403
        )

    def test_secretario_puede_crear_y_dar_baja(
        self, client_for_role, make_voluntario
    ):
        c = client_for_role(["secretario"])
        v = make_voluntario()
        # Crear.
        r = c.post(
            BASE,
            json={
                "nombre": "Nueva Persona",
                "telefono": "+34611111111",
                "municipio": "Zaragoza",
                "fecha_nacimiento": "1990-01-01",
                "email": "nueva.persona@example.com",
            },
        )
        assert r.status_code == 201
        # Dar de baja.
        assert c.delete(f"{BASE}/{v.id}").status_code == 200

    def test_tesorero_solo_lectura(self, client_for_role, voluntario):
        c = client_for_role(["tesorero"])
        # Lectura OK.
        assert c.get(BASE).status_code == 200
        assert c.get(f"{BASE}/{voluntario.id}").status_code == 200
        # Escritura prohibida.
        assert (
            c.patch(f"{BASE}/{voluntario.id}", json={"municipio": "x"}).status_code
            == 403
        )
        assert c.delete(f"{BASE}/{voluntario.id}").status_code == 403


# ---------------------------------------------------------------------------
# EN-02-05: asignación / baja de roles
# ---------------------------------------------------------------------------


def _rol_by_nombre(db_session, nombre: str) -> uuid.UUID:
    """Obtiene el id del rol seeded por el conftest, por su nombre."""

    from sqlmodel import select

    from app.models.rol import Rol

    rol = db_session.exec(select(Rol).where(Rol.nombre == nombre)).first()
    assert rol is not None, f"rol seeded {nombre!r} no encontrado en BD test"
    return rol.id


class TestAsignarRol:
    def test_asignar_rol_como_subjefe_devuelve_201(
        self, client_for_role, voluntario, db_session
    ):
        c = client_for_role(["subjefe_agrupacion"])
        rol_id = _rol_by_nombre(db_session, "jefe_equipo")
        r = c.post(
            f"{BASE}/{voluntario.id}/roles", json={"rol_id": str(rol_id)}
        )
        assert r.status_code == 201
        body = r.json()
        assert body["voluntario_id"] == str(voluntario.id)
        assert body["rol_id"] == str(rol_id)
        assert body["rol_nombre"] == "jefe_equipo"
        assert body["fecha_hasta"] is None

    def test_asignar_rol_sincroniza_con_keycloak(
        self,
        client_for_role,
        make_voluntario,
        db_session,
        fake_keycloak_admin,
    ):
        c = client_for_role(["subjefe_agrupacion"])
        v = make_voluntario(keycloak_id="kc-target-1")
        rol_id = _rol_by_nombre(db_session, "jefe_equipo")

        r = c.post(f"{BASE}/{v.id}/roles", json={"rol_id": str(rol_id)})
        assert r.status_code == 201
        assert ("kc-target-1", "jefe_equipo") in fake_keycloak_admin.roles_asignados

    def test_asignar_rol_sin_keycloak_id_no_llama_a_kc(
        self,
        client_for_role,
        make_voluntario,
        db_session,
        fake_keycloak_admin,
    ):
        c = client_for_role(["subjefe_agrupacion"])
        # Voluntario sin keycloak_id (pre-sync o aún no dado de alta en KC).
        v = make_voluntario(keycloak_id=None)
        rol_id = _rol_by_nombre(db_session, "jefe_equipo")

        r = c.post(f"{BASE}/{v.id}/roles", json={"rol_id": str(rol_id)})
        assert r.status_code == 201
        assert fake_keycloak_admin.roles_asignados == []

    def test_asignar_rol_como_voluntario_basico_es_403(
        self, authenticated_client, voluntario, db_session
    ):
        rol_id = _rol_by_nombre(db_session, "jefe_equipo")
        r = authenticated_client.post(
            f"{BASE}/{voluntario.id}/roles", json={"rol_id": str(rol_id)}
        )
        assert r.status_code == 403

    def test_asignar_rol_como_tesorero_es_403(
        self, client_for_role, voluntario, db_session
    ):
        # `tesorero` no tiene voluntarios.editar.
        c = client_for_role(["tesorero"])
        rol_id = _rol_by_nombre(db_session, "jefe_equipo")
        r = c.post(
            f"{BASE}/{voluntario.id}/roles", json={"rol_id": str(rol_id)}
        )
        assert r.status_code == 403

    def test_asignar_rol_a_voluntario_inexistente_es_404(
        self, client_for_role, db_session
    ):
        c = client_for_role(["subjefe_agrupacion"])
        rol_id = _rol_by_nombre(db_session, "jefe_equipo")
        r = c.post(
            f"{BASE}/{uuid.uuid4()}/roles", json={"rol_id": str(rol_id)}
        )
        assert r.status_code == 404

    def test_asignar_rol_inexistente_es_404(
        self, client_for_role, voluntario
    ):
        c = client_for_role(["subjefe_agrupacion"])
        r = c.post(
            f"{BASE}/{voluntario.id}/roles",
            json={"rol_id": str(uuid.uuid4())},
        )
        assert r.status_code == 404

    def test_asignar_rol_duplicado_es_409(
        self, client_for_role, voluntario, db_session
    ):
        c = client_for_role(["subjefe_agrupacion"])
        rol_id = _rol_by_nombre(db_session, "jefe_equipo")
        c.post(f"{BASE}/{voluntario.id}/roles", json={"rol_id": str(rol_id)})
        r = c.post(
            f"{BASE}/{voluntario.id}/roles", json={"rol_id": str(rol_id)}
        )
        assert r.status_code == 409


class TestQuitarRol:
    def test_quitar_rol_como_subjefe_devuelve_200_y_fecha_hasta(
        self, client_for_role, voluntario, db_session
    ):
        c = client_for_role(["subjefe_agrupacion"])
        rol_id = _rol_by_nombre(db_session, "jefe_equipo")
        c.post(f"{BASE}/{voluntario.id}/roles", json={"rol_id": str(rol_id)})

        r = c.delete(f"{BASE}/{voluntario.id}/roles/{rol_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["fecha_hasta"] is not None
        assert body["rol_nombre"] == "jefe_equipo"

    def test_quitar_rol_sincroniza_con_keycloak(
        self,
        client_for_role,
        make_voluntario,
        db_session,
        fake_keycloak_admin,
    ):
        c = client_for_role(["subjefe_agrupacion"])
        v = make_voluntario(keycloak_id="kc-target-2")
        rol_id = _rol_by_nombre(db_session, "jefe_equipo")
        c.post(f"{BASE}/{v.id}/roles", json={"rol_id": str(rol_id)})

        r = c.delete(f"{BASE}/{v.id}/roles/{rol_id}")
        assert r.status_code == 200
        assert ("kc-target-2", "jefe_equipo") in fake_keycloak_admin.roles_revocados

    def test_quitar_rol_no_asignado_es_404(
        self, client_for_role, voluntario, db_session
    ):
        c = client_for_role(["subjefe_agrupacion"])
        rol_id = _rol_by_nombre(db_session, "jefe_equipo")
        # Sin asignación previa.
        r = c.delete(f"{BASE}/{voluntario.id}/roles/{rol_id}")
        assert r.status_code == 404

    def test_quitar_rol_dos_veces_segunda_es_404(
        self, client_for_role, voluntario, db_session
    ):
        c = client_for_role(["subjefe_agrupacion"])
        rol_id = _rol_by_nombre(db_session, "jefe_equipo")
        c.post(f"{BASE}/{voluntario.id}/roles", json={"rol_id": str(rol_id)})
        c.delete(f"{BASE}/{voluntario.id}/roles/{rol_id}")
        # Ya cerrada (fecha_hasta poblada) → no hay asignación activa.
        r = c.delete(f"{BASE}/{voluntario.id}/roles/{rol_id}")
        assert r.status_code == 404

    def test_quitar_rol_como_voluntario_basico_es_403(
        self, authenticated_client, voluntario, db_session
    ):
        rol_id = _rol_by_nombre(db_session, "jefe_equipo")
        r = authenticated_client.delete(
            f"{BASE}/{voluntario.id}/roles/{rol_id}"
        )
        assert r.status_code == 403

    def test_quitar_rol_a_voluntario_inexistente_es_404(
        self, client_for_role, db_session
    ):
        c = client_for_role(["subjefe_agrupacion"])
        rol_id = _rol_by_nombre(db_session, "jefe_equipo")
        r = c.delete(f"{BASE}/{uuid.uuid4()}/roles/{rol_id}")
        assert r.status_code == 404

    def test_reasignar_rol_tras_quitar_funciona(
        self, client_for_role, voluntario, db_session
    ):
        """Quitar y volver a asignar el mismo rol debe ser válido (asignación nueva)."""

        c = client_for_role(["subjefe_agrupacion"])
        rol_id = _rol_by_nombre(db_session, "jefe_equipo")
        c.post(f"{BASE}/{voluntario.id}/roles", json={"rol_id": str(rol_id)})
        c.delete(f"{BASE}/{voluntario.id}/roles/{rol_id}")
        r = c.post(
            f"{BASE}/{voluntario.id}/roles", json={"rol_id": str(rol_id)}
        )
        assert r.status_code == 201
        # La nueva asignación tiene fecha_hasta=None (no es la anterior).
        assert r.json()["fecha_hasta"] is None


class TestSyncKeycloakFallido:
    def test_si_kc_falla_en_asignacion_no_se_persiste_en_bd(
        self,
        client_for_role,
        make_voluntario,
        db_session,
    ):
        """Patrón EN-02-03: KC antes de BD. Si KC falla, BD no se toca."""

        # Sustituimos el fake por uno que falla.
        from tests.conftest import FakeKeycloakAdmin

        failing = FakeKeycloakAdmin()

        # Truco: hackeamos directamente el método para que falle.
        def _fail(*args, **kwargs):
            from app.services.keycloak_admin import KeycloakAdminError

            raise KeycloakAdminError("test sync failure")

        failing.asignar_rol_realm = _fail

        from app.main import app
        from app.services.keycloak_admin import get_keycloak_admin

        app.dependency_overrides[get_keycloak_admin] = lambda: failing

        try:
            c = client_for_role(["subjefe_agrupacion"])
            v = make_voluntario(keycloak_id="kc-target-3")
            rol_id = _rol_by_nombre(db_session, "jefe_equipo")
            r = c.post(
                f"{BASE}/{v.id}/roles", json={"rol_id": str(rol_id)}
            )
            assert r.status_code == 502

            # Comprobar que NO se ha persistido la asignación.
            from app.repositories import voluntarios as repo

            assert (
                repo.get_asignacion_activa(
                    db_session, voluntario_id=v.id, rol_id=rol_id
                )
                is None
            )
        finally:
            # El cliente del fixture habrá restablecido los overrides al
            # finalizar el test, pero por si acaso.
            pass
