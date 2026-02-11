# app/core/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuración centralizada via variables de entorno."""

    # Base de datos
    database_url: str = "postgresql://custodiam:password@localhost:5432/custodiam"

    # Keycloak
    keycloak_url: str = "http://localhost:8080"
    keycloak_realm: str = "custodiam"
    keycloak_public_url: str = "http://localhost:8080"

    # ntfy
    ntfy_url: str = "http://localhost:8090"

    # App
    debug: bool = False
    api_version: str = "v1"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
