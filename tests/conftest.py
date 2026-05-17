# tests/conftest.py
import pytest
from fastapi.testclient import TestClient

from app.core.security import get_current_user
from app.main import app
from app.schemas.auth import CurrentUser


@pytest.fixture
def client():
    return TestClient(app)


def _make_fake_user(
    sub: str = "test-user-id",
    email: str = "test@custodiam.es",
    preferred_username: str = "testuser",
    roles: list[str] | None = None,
    given_name: str = "Test",
    family_name: str = "User",
) -> CurrentUser:
    return CurrentUser(
        sub=sub,
        email=email,
        preferred_username=preferred_username,
        roles=roles or ["voluntario"],
        given_name=given_name,
        family_name=family_name,
    )


@pytest.fixture
def authenticated_client(client):
    """Cliente autenticado como voluntario (inyecta CurrentUser falso sin tocar Keycloak)."""
    app.dependency_overrides[get_current_user] = _make_fake_user
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def admin_client(client):
    """Cliente autenticado como admin + coordinador."""
    app.dependency_overrides[get_current_user] = lambda: _make_fake_user(
        sub="admin-user-id",
        email="admin@custodiam.es",
        preferred_username="admin",
        roles=["admin", "coordinador"],
        given_name="Admin",
        family_name="Custodiam",
    )
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def jefe_client(client):
    """Cliente autenticado como jefe_equipo + voluntario."""
    app.dependency_overrides[get_current_user] = lambda: _make_fake_user(
        sub="jefe-user-id",
        email="jefe@custodiam.es",
        preferred_username="cjefe",
        roles=["jefe_equipo", "voluntario"],
        given_name="Carlos",
        family_name="López",
    )
    yield client
    app.dependency_overrides.clear()
