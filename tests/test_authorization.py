"""Tests de los endpoints que dependen del sistema RBAC."""

from app.core.permissions import Permission


def test_me_permissions_sin_token(client):
    response = client.get("/api/v1/me/permissions")
    assert response.status_code == 401


def test_me_permissions_como_voluntario(authenticated_client):
    response = authenticated_client.get("/api/v1/me/permissions")
    assert response.status_code == 200
    data = response.json()
    assert data["roles"] == ["voluntario"]
    perms = data["permissions"]
    assert Permission.SERVICIOS_APUNTARSE_PROPIO.value in perms
    assert Permission.FICHAJE_FICHAR_PROPIO.value in perms
    # Y no los de jefatura.
    assert Permission.SERVICIOS_CREAR_PREVENTIVO.value not in perms
    assert Permission.VOLUNTARIOS_CREAR.value not in perms


def test_me_permissions_como_admin_mas_coordinador(admin_client):
    # La cuenta admin del piloto lleva además coordinador
    # (verificado en EN-01-03). Debe ver tanto técnicos como operativos.
    response = admin_client.get("/api/v1/me/permissions")
    assert response.status_code == 200
    data = response.json()
    perms = data["permissions"]
    # Técnicos del admin.
    assert Permission.SISTEMA_PANEL_ADMIN.value in perms
    assert Permission.SISTEMA_BACKUPS.value in perms
    # Operativos del coordinador.
    assert Permission.SERVICIOS_CREAR_EMERGENCIA.value in perms
    assert Permission.VOLUNTARIOS_CREAR.value in perms


def test_me_permissions_estan_ordenados_alfabeticamente(authenticated_client):
    response = authenticated_client.get("/api/v1/me/permissions")
    perms = response.json()["permissions"]
    assert perms == sorted(perms)


def test_endpoint_voluntarios_listar_sin_token(client):
    response = client.get("/api/v1/voluntarios")
    assert response.status_code == 401


def test_endpoint_voluntarios_listar_como_voluntario_tiene_permiso(
    authenticated_client,
):
    # voluntario tiene voluntarios.listar (decisión 4 + matriz E02).
    response = authenticated_client.get("/api/v1/voluntarios")
    assert response.status_code == 200


def test_endpoint_voluntarios_listar_como_admin_puro_es_403(client_for_role):
    # admin puro NO tiene voluntarios.listar (decisión 1).
    c = client_for_role(["admin"])
    response = c.get("/api/v1/voluntarios")
    assert response.status_code == 403
    assert Permission.VOLUNTARIOS_LISTAR.value in response.json()["detail"]


def test_endpoint_voluntarios_listar_como_practicas_es_403(client_for_role):
    # voluntario_practicas no aparece en la matriz de voluntarios.listar.
    c = client_for_role(["voluntario_practicas"])
    response = c.get("/api/v1/voluntarios")
    assert response.status_code == 403


def test_endpoint_voluntarios_listar_como_tesorero_tiene_permiso(client_for_role):
    # tesorero tiene voluntarios.listar (decisión 8: lectura amplia).
    c = client_for_role(["tesorero"])
    response = c.get("/api/v1/voluntarios")
    assert response.status_code == 200


def test_has_permission_como_metodo_del_schema():
    from app.schemas.auth import CurrentUser

    user = CurrentUser(sub="1", email="a@b.com", roles=["voluntario"])
    assert user.has_permission(Permission.SERVICIOS_APUNTARSE_PROPIO) is True
    assert user.has_permission(Permission.VOLUNTARIOS_CREAR) is False


def test_has_permission_para_usuario_multirol():
    from app.schemas.auth import CurrentUser

    user = CurrentUser(sub="1", email="a@b.com", roles=["admin", "subjefe_agrupacion"])
    assert user.has_permission(Permission.SISTEMA_PANEL_ADMIN) is True
    assert user.has_permission(Permission.VOLUNTARIOS_CREAR) is True
