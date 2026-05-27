"""Router del catálogo de roles (EN-02-05 follow-up).

Endpoint sencillo: lista todos los roles del realm de Keycloak espejados
en la tabla local ``roles``. Lo necesita el frontend para construir el
selector de rol del formulario de asignación
(POST /voluntarios/{id}/roles).

No requiere permiso específico: cualquier usuario autenticado puede ver
el catálogo. Razón: el catálogo es pequeño, público dentro del realm
(el JWT ya lleva la lista de roles del usuario actual), y los formularios
de filtro / búsqueda de varios módulos lo necesitan. Restringirlo con
``voluntarios.editar`` impediría que un voluntario básico viera el
nombre del rol que él mismo tiene asignado.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.core.database import get_session
from app.core.security import get_current_user
from app.repositories import voluntarios as repo
from app.schemas.auth import CurrentUser
from app.schemas.voluntario import RolResponse

router = APIRouter(prefix="/roles", tags=["roles"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get(
    "",
    response_model=list[RolResponse],
    summary="Listar el catálogo de roles del realm (EN-02-05)",
)
def listar_roles_catalogo(
    session: SessionDep,
    _: Annotated[CurrentUser, Depends(get_current_user)],
):
    """Devuelve todos los roles del catálogo ordenados por nivel ascendente."""

    return repo.list_roles_catalogo(session)
