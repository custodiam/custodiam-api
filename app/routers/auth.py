from fastapi import APIRouter, Depends

from app.core.permissions import Permission, permissions_for_roles
from app.core.security import get_current_user, require_permission, require_role
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


@router.get("/me/permissions")
def my_permissions(user: CurrentUser = Depends(get_current_user)):
    """Lista los permisos efectivos del usuario actual.

    El frontend la usa para precalcular qué widgets condicionales
    enseñar tras login (ver ``CurrentUserNotifier`` en el cliente).
    El JWT NO lleva permisos: el mapa rol→permisos vive en código.
    """

    perms = permissions_for_roles(user.roles)
    return {
        "roles": user.roles,
        "permissions": sorted(p.value for p in perms),
    }


@router.get("/voluntarios/test")
def voluntarios_listar_test(
    user: CurrentUser = Depends(
        require_permission(Permission.VOLUNTARIOS_LISTAR),
    ),
):
    """Endpoint de prueba protegido por permiso.

    Sirve como verificación end-to-end de ``require_permission``
    mientras E02 (módulo voluntarios) no esté implementado. Se
    sustituye por el endpoint real cuando llegue US-02-09.
    """

    return {
        "message": f"{user.full_name}, tienes permiso para listar voluntarios",
        "permission_required": Permission.VOLUNTARIOS_LISTAR.value,
    }
