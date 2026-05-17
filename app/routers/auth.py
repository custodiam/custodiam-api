from fastapi import APIRouter, Depends

from app.core.security import get_current_user, require_role
from app.schemas.auth import CurrentUser

router = APIRouter(tags=["auth"])


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)):
    return {
        "sub": user.sub,
        "email": user.email,
        "preferred_username": user.preferred_username,
        "roles": user.roles,
        "given_name": user.given_name,
        "family_name": user.family_name,
        "full_name": user.full_name,
    }


@router.get("/me/roles")
def my_roles(user: CurrentUser = Depends(get_current_user)):
    return {
        "roles": user.roles,
        "is_admin": user.has_role("admin"),
        "is_jefe": user.has_any_role([
            "jefe_equipo",
            "jefe_grupo",
            "jefe_seccion",
            "jefe_unidad",
            "jefe_agrupacion",
            "subjefe_agrupacion",
            "coordinador",
        ]),
    }


@router.get("/admin/test")
def admin_test(user: CurrentUser = Depends(require_role(["admin"]))):
    return {
        "message": f"Hola {user.full_name}, tienes acceso de administrador",
        "your_roles": user.roles,
    }
