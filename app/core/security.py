"""Validación JWT offline con PyJWT + JWKS de Keycloak.

PyJWKClient cachea las claves públicas durante 5 minutos (lifespan=300).
La inicialización es lazy: no se hace ninguna request hasta que llega el
primer token, por lo que los tests funcionan sin Keycloak corriendo.
"""

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2AuthorizationCodeBearer
from jwt import PyJWKClient

from app.core.config import settings
from app.core.permissions import Permission, permissions_for_roles
from app.schemas.auth import CurrentUser

# OAuth2AuthorizationCodeBearer documenta el flujo real (Authorization
# Code + PKCE) en el OpenAPI generado, así que Swagger UI muestra el
# botón "Authorize" como redirect-and-callback en lugar del formulario
# user+password incorrecto que dibujaría OAuth2PasswordBearer. La
# extracción del header `Authorization: Bearer <token>` en runtime es
# idéntica entre los dos schemes.
oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl=(
        f"{settings.keycloak_public_url}/realms/{settings.keycloak_realm}"
        f"/protocol/openid-connect/auth"
    ),
    tokenUrl=(
        f"{settings.keycloak_public_url}/realms/{settings.keycloak_realm}"
        f"/protocol/openid-connect/token"
    ),
    refreshUrl=(
        f"{settings.keycloak_public_url}/realms/{settings.keycloak_realm}"
        f"/protocol/openid-connect/token"
    ),
    auto_error=True,
)

_jwks_client = PyJWKClient(settings.keycloak_jwks_url, lifespan=300)


def _decode_token(token: str) -> dict:
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.keycloak_issuer,
            options={
                "verify_exp": True,
                "verify_iss": True,
                # Keycloak pone "account" como aud por defecto. En lugar
                # de habilitar verify_aud (que exigiría configurar un
                # audience-resolve mapper en Keycloak), validamos `azp`
                # (Authorized Party) abajo. El `azp` lo rellena Keycloak
                # con el client_id del cliente que solicitó el token,
                # así que es la fuente fiable para restringir la API a
                # tokens emitidos para `custodiam-app`.
                "verify_aud": False,
                "require": ["exp", "iss", "sub"],
            },
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidIssuerError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Issuer del token no válido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWKClientError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No se pudieron obtener las claves públicas de Keycloak",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token no válido: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Defensa en profundidad: rechazar tokens emitidos para otros clientes
    # del realm. Sin esta verificación, cualquier futuro cliente OAuth del
    # mismo realm podría obtener tokens válidos para este backend.
    azp = payload.get("azp")
    if azp != settings.keycloak_authorized_party:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                f"Token no emitido para esta aplicación "
                f"(azp={azp!r}, esperado={settings.keycloak_authorized_party!r})"
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


async def get_current_user(token: str = Depends(oauth2_scheme)) -> CurrentUser:
    payload = _decode_token(token)
    return CurrentUser(
        sub=payload.get("sub", ""),
        email=payload.get("email", ""),
        preferred_username=payload.get("preferred_username", ""),
        roles=payload.get("roles", []),
        given_name=payload.get("given_name", ""),
        family_name=payload.get("family_name", ""),
    )


def require_role(allowed_roles: list[str]):
    """Factory de dependency: 403 si el usuario no tiene ninguno de los roles.

    Reservado para casos donde la matriz de permisos quede sobredimensionada
    (típicamente: endpoints puramente técnicos de ``admin``). Para todo lo
    demás, preferir ``require_permission``.
    """

    async def _check_role(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_any_role(allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Se requiere uno de los roles: {', '.join(allowed_roles)}",
            )
        return user

    return _check_role


def has_permission(user: CurrentUser, permission: Permission) -> bool:
    """True si alguno de los roles del usuario otorga el permiso."""

    return permission in permissions_for_roles(user.roles)


def require_permission(permission: Permission):
    """Factory de dependency: 403 si el usuario no tiene el permiso.

    Patrón preferido sobre ``require_role`` (ver decisión 12 del documento
    ``docs/trabajo/backlog/RBAC_v0.1.0.md``). Los endpoints declaran qué
    permiso necesitan; el mapa rol→permiso vive en ``app/core/permissions.py``.
    """

    async def _check_permission(
        user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if not has_permission(user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Se requiere el permiso: {permission.value}",
            )
        return user

    return _check_permission
