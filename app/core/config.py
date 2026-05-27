# app/core/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuración centralizada via variables de entorno."""

    # Base de datos. El prefijo `+psycopg` es obligatorio: el dialect
    # canónico para psycopg 3 en SQLAlchemy 2.x. Sin él, SQLAlchemy
    # busca psycopg2 (no instalado) y falla con un ImportError opaco
    # antes de que ninguna ruta responda.
    database_url: str = (
        "postgresql+psycopg://custodiam:password@localhost:5432/custodiam"
    )

    # Keycloak
    keycloak_url: str = "http://localhost:8080"
    keycloak_realm: str = "custodiam"
    keycloak_public_url: str = "http://localhost:8080"
    # Authorized Party esperado en el claim `azp` del JWT. Keycloak lo
    # rellena con el client_id que solicitó el token. Coincide con el
    # cliente público declarado en `realm-custodiam.json` para la app
    # Flutter (`custodiam-app`). Si Keycloak emite un token para otro
    # cliente del realm, el backend lo rechaza.
    keycloak_authorized_party: str = "custodiam-app"

    # Credenciales para la Admin API de Keycloak (EN-02-03).
    # Si `keycloak_admin_password` está vacío, el cliente de Admin opera
    # en modo "deshabilitado" (no realiza llamadas y devuelve None en
    # las operaciones), de forma que tests, desarrollo offline y entornos
    # de aún-no-configurado puedan ejecutarse sin necesidad de tocar KC.
    keycloak_admin_username: str = "admin"
    keycloak_admin_password: str = ""
    # `admin-cli` es el cliente built-in del realm master que tiene
    # permisos de administración. No requiere configuración extra.
    keycloak_admin_client_id: str = "admin-cli"

    # ntfy
    ntfy_url: str = "http://localhost:8090"

    # App
    debug: bool = False
    api_version: str = "v1"

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def keycloak_issuer(self) -> str:
        """Issuer esperado en los tokens JWT (URL pública: la que Keycloak pone en `iss`)."""
        return f"{self.keycloak_public_url}/realms/{self.keycloak_realm}"

    @property
    def keycloak_jwks_url(self) -> str:
        """Endpoint JWKS para descargar claves públicas (URL interna: red Docker)."""
        return (
            f"{self.keycloak_url}/realms/{self.keycloak_realm}"
            f"/protocol/openid-connect/certs"
        )


settings = Settings()
