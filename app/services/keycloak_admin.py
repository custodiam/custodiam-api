"""Cliente HTTP para la Admin API de Keycloak (EN-02-03).

Encapsula las operaciones de sincronización Keycloak ↔ BD que necesitan
los flujos de alta, baja y cambio de rol del módulo voluntarios. La
clase :class:`KeycloakAdminClient` mantiene en caché el access token
del cliente `admin-cli` y lo renueva cuando expira (~60 s de margen).

Modo deshabilitado
------------------

Si `settings.keycloak_admin_password` está vacío, todas las operaciones
de escritura devuelven ``None`` sin contactar a Keycloak. Esto permite
arrancar la API en entornos sin la Admin API configurada (CI, primera
ejecución local) sin reescribir el flujo del Service.
"""

from __future__ import annotations

import logging
import time

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class KeycloakAdminError(Exception):
    """La Admin API de Keycloak devolvió un error o fue inalcanzable."""


class KeycloakAdminClient:
    """Cliente síncrono de la Admin API de Keycloak.

    Los endpoints concretos están en
    `${KEYCLOAK_URL}/admin/realms/${KEYCLOAK_REALM}/...`. La autenticación
    se hace contra el realm `master` con el cliente built-in `admin-cli`.
    """

    # Margen de seguridad para considerar el token "casi caducado".
    _TOKEN_REFRESH_MARGIN_SECONDS: float = 30.0

    def __init__(
        self,
        *,
        base_url: str | None = None,
        realm: str | None = None,
        admin_username: str | None = None,
        admin_password: str | None = None,
        admin_client_id: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base_url = (base_url or settings.keycloak_url).rstrip("/")
        self._realm = realm or settings.keycloak_realm
        self._admin_username = admin_username or settings.keycloak_admin_username
        self._admin_password = (
            admin_password
            if admin_password is not None
            else settings.keycloak_admin_password
        )
        self._admin_client_id = admin_client_id or settings.keycloak_admin_client_id
        self._http = http_client or httpx.Client(timeout=10.0)
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """True si el cliente está configurado para llamar a Keycloak.

        El criterio operativo: hay una contraseña de admin configurada.
        Sin ella no podemos autenticar, así que evitamos intentarlo.
        """

        return bool(self._admin_password)

    # ------------------------------------------------------------------
    # Token de Admin
    # ------------------------------------------------------------------

    def _get_admin_token(self) -> str:
        """Obtiene o renueva el access token del cliente admin-cli."""

        now = time.monotonic()
        if self._token and now < self._token_expires_at - self._TOKEN_REFRESH_MARGIN_SECONDS:
            return self._token

        token_url = (
            f"{self._base_url}/realms/master/protocol/openid-connect/token"
        )
        try:
            response = self._http.post(
                token_url,
                data={
                    "grant_type": "password",
                    "client_id": self._admin_client_id,
                    "username": self._admin_username,
                    "password": self._admin_password,
                },
            )
        except httpx.HTTPError as e:
            raise KeycloakAdminError(
                f"No se pudo contactar con Keycloak para obtener el token de admin: {e}"
            ) from e

        if response.status_code != 200:
            raise KeycloakAdminError(
                f"Token de admin denegado por Keycloak (HTTP {response.status_code})"
            )

        payload = response.json()
        access_token = payload.get("access_token")
        expires_in = float(payload.get("expires_in", 60))
        if not access_token:
            raise KeycloakAdminError(
                "La respuesta del token de admin no contenía `access_token`"
            )

        self._token = access_token
        self._token_expires_at = now + expires_in
        return access_token

    # ------------------------------------------------------------------
    # Operaciones CRUD sobre usuarios
    # ------------------------------------------------------------------

    def crear_usuario(
        self,
        *,
        username: str,
        email: str | None,
        given_name: str,
        family_name: str,
        password_temporal: str | None = None,
    ) -> str | None:
        """Crea un usuario en el realm de Custodiam y devuelve su `id`.

        Si el cliente está deshabilitado (sin password configurada),
        devuelve ``None`` sin contactar con Keycloak.

        El password temporal se marca como ``temporary=true`` para forzar
        el cambio en el primer login.
        """

        if not self.enabled:
            logger.debug(
                "KeycloakAdminClient deshabilitado: omitiendo crear_usuario(%s)",
                username,
            )
            return None

        token = self._get_admin_token()
        users_url = f"{self._base_url}/admin/realms/{self._realm}/users"
        body: dict = {
            "username": username,
            "enabled": True,
            "firstName": given_name,
            "lastName": family_name,
        }
        if email:
            body["email"] = email
            body["emailVerified"] = False
        if password_temporal:
            body["credentials"] = [
                {
                    "type": "password",
                    "value": password_temporal,
                    "temporary": True,
                }
            ]

        try:
            response = self._http.post(
                users_url,
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as e:
            raise KeycloakAdminError(
                f"Error de red al crear usuario en Keycloak: {e}"
            ) from e

        if response.status_code == 409:
            raise KeycloakAdminError(
                f"Ya existe un usuario en Keycloak con username={username!r}"
            )
        if response.status_code not in (201, 204):
            raise KeycloakAdminError(
                f"Keycloak rechazó el alta de usuario (HTTP {response.status_code}): "
                f"{response.text}"
            )

        # La Admin API devuelve el id en el header Location:
        # ".../admin/realms/{realm}/users/{kc_id}". Lo extraemos.
        location = response.headers.get("Location") or response.headers.get("location")
        if not location:
            raise KeycloakAdminError(
                "Keycloak no devolvió el header `Location` con el id del usuario"
            )
        return location.rstrip("/").rsplit("/", 1)[-1]

    def desactivar_usuario(self, keycloak_id: str) -> None:
        """Pone `enabled=false` en el usuario (no lo borra)."""

        if not self.enabled:
            logger.debug(
                "KeycloakAdminClient deshabilitado: omitiendo desactivar_usuario(%s)",
                keycloak_id,
            )
            return None

        token = self._get_admin_token()
        url = f"{self._base_url}/admin/realms/{self._realm}/users/{keycloak_id}"

        try:
            response = self._http.put(
                url,
                json={"enabled": False},
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as e:
            raise KeycloakAdminError(
                f"Error de red al desactivar usuario en Keycloak: {e}"
            ) from e

        if response.status_code == 404:
            # Tolerar idempotencia: si el usuario ya no existe en KC,
            # consideramos la desactivación cumplida.
            logger.warning(
                "El usuario Keycloak %s no existe; se considera desactivado.",
                keycloak_id,
            )
            return None
        if response.status_code not in (200, 204):
            raise KeycloakAdminError(
                f"Keycloak rechazó la desactivación (HTTP {response.status_code}): "
                f"{response.text}"
            )
        return None

    def asignar_rol_realm(self, keycloak_id: str, role_name: str) -> None:
        """Añade un rol del realm al usuario."""

        if not self.enabled:
            logger.debug(
                "KeycloakAdminClient deshabilitado: omitiendo asignar_rol_realm(%s, %s)",
                keycloak_id,
                role_name,
            )
            return None

        token = self._get_admin_token()
        headers = {"Authorization": f"Bearer {token}"}

        role_url = (
            f"{self._base_url}/admin/realms/{self._realm}/roles/{role_name}"
        )
        try:
            role_response = self._http.get(role_url, headers=headers)
        except httpx.HTTPError as e:
            raise KeycloakAdminError(
                f"Error de red al obtener rol {role_name} en Keycloak: {e}"
            ) from e
        if role_response.status_code != 200:
            raise KeycloakAdminError(
                f"No se pudo obtener el rol {role_name} (HTTP {role_response.status_code})"
            )

        mappings_url = (
            f"{self._base_url}/admin/realms/{self._realm}/users/{keycloak_id}"
            f"/role-mappings/realm"
        )
        try:
            assign_response = self._http.post(
                mappings_url,
                json=[role_response.json()],
                headers=headers,
            )
        except httpx.HTTPError as e:
            raise KeycloakAdminError(
                f"Error de red al asignar rol {role_name} en Keycloak: {e}"
            ) from e
        if assign_response.status_code not in (200, 204):
            raise KeycloakAdminError(
                f"Keycloak rechazó la asignación de rol "
                f"(HTTP {assign_response.status_code}): {assign_response.text}"
            )
        return None

    def quitar_rol_realm(self, keycloak_id: str, role_name: str) -> None:
        """Revoca un rol del realm al usuario."""

        if not self.enabled:
            logger.debug(
                "KeycloakAdminClient deshabilitado: omitiendo quitar_rol_realm(%s, %s)",
                keycloak_id,
                role_name,
            )
            return None

        token = self._get_admin_token()
        headers = {"Authorization": f"Bearer {token}"}

        role_url = (
            f"{self._base_url}/admin/realms/{self._realm}/roles/{role_name}"
        )
        try:
            role_response = self._http.get(role_url, headers=headers)
        except httpx.HTTPError as e:
            raise KeycloakAdminError(
                f"Error de red al obtener rol {role_name} en Keycloak: {e}"
            ) from e
        if role_response.status_code != 200:
            raise KeycloakAdminError(
                f"No se pudo obtener el rol {role_name} (HTTP {role_response.status_code})"
            )

        mappings_url = (
            f"{self._base_url}/admin/realms/{self._realm}/users/{keycloak_id}"
            f"/role-mappings/realm"
        )
        try:
            del_response = self._http.request(
                "DELETE",
                mappings_url,
                json=[role_response.json()],
                headers=headers,
            )
        except httpx.HTTPError as e:
            raise KeycloakAdminError(
                f"Error de red al revocar rol {role_name} en Keycloak: {e}"
            ) from e
        if del_response.status_code not in (200, 204):
            raise KeycloakAdminError(
                f"Keycloak rechazó la revocación de rol "
                f"(HTTP {del_response.status_code}): {del_response.text}"
            )
        return None


# ---------------------------------------------------------------------------
# Dependency FastAPI
# ---------------------------------------------------------------------------


def get_keycloak_admin() -> KeycloakAdminClient:
    """Factoría inyectable como `Depends` en routers."""

    return KeycloakAdminClient()
