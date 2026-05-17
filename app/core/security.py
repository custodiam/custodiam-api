"""Validación JWT offline con PyJWT + JWKS de Keycloak.

PyJWKClient cachea las claves públicas durante 5 minutos (lifespan=300).
La inicialización es lazy: no se hace ninguna request hasta que llega el
primer token, por lo que los tests funcionan sin Keycloak corriendo.
"""

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt import PyJWKClient

from app.core.config import settings
from app.schemas.auth import CurrentUser

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=(
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
                # Keycloak pone "account" como aud por defecto, no nuestro client_id.
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
    """Factory de dependency: 403 si el usuario no tiene ninguno de los roles."""

    async def _check_role(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_any_role(allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Se requiere uno de los roles: {', '.join(allowed_roles)}",
            )
        return user

    return _check_role
