"""Tests E2E del router de roles + GET /voluntarios/{id}/roles
(EN-02-05 follow-up para desbloquear el frontend).
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.models.voluntario_rol import VoluntarioRol

# ---------------------------------------------------------------------------
# GET /api/v1/roles
# ---------------------------------------------------------------------------


def _rol_id_por_nombre(db_session, nombre: str) -> uuid.UUID:
    from sqlmodel import select

    from app.models.rol import Rol

    rol = db_session.exec(select(Rol).where(Rol.nombre == nombre)).first()
    assert rol is not None, f"rol seeded {nombre!r} no encontrado"
    return rol.id


class TestListarRolesCatalogo:
    def test_sin_token_es_401(self, client):
        assert client.get("/api/v1/roles").status_code == 401

    def test_voluntario_basico_puede_ver_catalogo(
        self, authenticated_client
    ):
        r = authenticated_client.get("/api/v1/roles")
        assert r.status_code == 200
        items = r.json()
        # El conftest siembra 4 roles: voluntario, jefe_equipo, jefe_agrupacion, coordinador.
        nombres = {item["nombre"] for item in items}
        assert {"voluntario", "jefe_equipo", "jefe_agrupacion", "coordinador"}.issubset(
            nombres
        )

    def test_orden_por_nivel_ascendente(self, authenticated_client):
        r = authenticated_client.get("/api/v1/roles")
        niveles = [item["nivel"] for item in r.json()]
        assert niveles == sorted(niveles)

    def test_response_expone_id_nombre_nivel(self, authenticated_client):
        r = authenticated_client.get("/api/v1/roles")
        item = r.json()[0]
        assert "id" in item
        assert "nombre" in item
        assert "nivel" in item
        # Permisos NO se exponen (ADR-013 lockstep).
        assert "permisos" not in item


# ---------------------------------------------------------------------------
# GET /api/v1/voluntarios/{id}/roles
# ---------------------------------------------------------------------------


@pytest.fixture
def voluntario_con_dos_roles(db_session, voluntario):
    """Voluntario con dos asignaciones activas seeded por el conftest."""

    rol_voluntario = _rol_id_por_nombre(db_session, "voluntario")
    rol_jefe = _rol_id_por_nombre(db_session, "jefe_equipo")

    db_session.add_all([
        VoluntarioRol(
            voluntario_id=voluntario.id,
            rol_id=rol_voluntario,
            fecha_desde=date(2026, 1, 1),
        ),
        VoluntarioRol(
            voluntario_id=voluntario.id,
            rol_id=rol_jefe,
            fecha_desde=date(2026, 3, 1),
        ),
    ])
    db_session.commit()
    return voluntario


class TestListarRolesVoluntario:
    def test_sin_token_es_401(self, client, voluntario):
        r = client.get(f"/api/v1/voluntarios/{voluntario.id}/roles")
        assert r.status_code == 401

    def test_voluntario_basico_no_puede_ver_roles_de_otro(
        self, authenticated_client, voluntario
    ):
        # `voluntario` (rol básico) NO tiene `voluntarios.ver_ficha`.
        r = authenticated_client.get(
            f"/api/v1/voluntarios/{voluntario.id}/roles"
        )
        assert r.status_code == 403

    def test_jefe_puede_ver_roles(
        self, jefe_client, voluntario_con_dos_roles
    ):
        r = jefe_client.get(
            f"/api/v1/voluntarios/{voluntario_con_dos_roles.id}/roles"
        )
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 2
        nombres = {item["rol_nombre"] for item in items}
        assert nombres == {"voluntario", "jefe_equipo"}

    def test_voluntario_sin_roles_devuelve_lista_vacia(
        self, jefe_client, voluntario
    ):
        r = jefe_client.get(f"/api/v1/voluntarios/{voluntario.id}/roles")
        assert r.status_code == 200
        assert r.json() == []

    def test_voluntario_inexistente_es_404(self, jefe_client):
        r = jefe_client.get(f"/api/v1/voluntarios/{uuid.uuid4()}/roles")
        assert r.status_code == 404

    def test_roles_cerrados_no_aparecen(
        self, jefe_client, db_session, voluntario
    ):
        """Solo asignaciones activas (fecha_hasta IS NULL)."""

        rol_voluntario = _rol_id_por_nombre(db_session, "voluntario")
        db_session.add(
            VoluntarioRol(
                voluntario_id=voluntario.id,
                rol_id=rol_voluntario,
                fecha_desde=date(2026, 1, 1),
                fecha_hasta=date(2026, 3, 1),
            )
        )
        db_session.commit()

        r = jefe_client.get(f"/api/v1/voluntarios/{voluntario.id}/roles")
        assert r.status_code == 200
        assert r.json() == []
