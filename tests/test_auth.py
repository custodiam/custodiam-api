"""Tests para endpoints de autenticación y autorización."""


def test_me_without_token(client):
    response = client.get("/api/v1/me")
    assert response.status_code == 401


def test_me_as_voluntario(authenticated_client):
    response = authenticated_client.get("/api/v1/me")
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@custodiam.es"
    assert data["preferred_username"] == "testuser"
    assert data["given_name"] == "Test"
    assert data["family_name"] == "User"
    assert data["full_name"] == "Test User"
    assert "voluntario" in data["roles"]


def test_me_roles_as_voluntario(authenticated_client):
    response = authenticated_client.get("/api/v1/me/roles")
    assert response.status_code == 200
    data = response.json()
    assert data["is_admin"] is False
    assert data["is_jefe"] is False
    assert "voluntario" in data["roles"]


def test_me_roles_as_admin(admin_client):
    response = admin_client.get("/api/v1/me/roles")
    assert response.status_code == 200
    data = response.json()
    assert data["is_admin"] is True


def test_me_roles_as_jefe(jefe_client):
    response = jefe_client.get("/api/v1/me/roles")
    assert response.status_code == 200
    data = response.json()
    assert data["is_jefe"] is True
    assert data["is_admin"] is False


def test_admin_endpoint_as_admin(admin_client):
    response = admin_client.get("/api/v1/admin/test")
    assert response.status_code == 200
    data = response.json()
    assert "administrador" in data["message"]


def test_admin_endpoint_as_voluntario(authenticated_client):
    response = authenticated_client.get("/api/v1/admin/test")
    assert response.status_code == 403


def test_admin_endpoint_without_token(client):
    response = client.get("/api/v1/admin/test")
    assert response.status_code == 401
