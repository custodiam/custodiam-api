from pydantic import BaseModel

from app.core.permissions import Permission, permissions_for_roles


class CurrentUser(BaseModel):
    """Usuario autenticado extraído del access token JWT de Keycloak."""

    sub: str
    email: str
    preferred_username: str = ""
    roles: list[str] = []
    given_name: str = ""
    family_name: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.given_name} {self.family_name}".strip()

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def has_any_role(self, roles: list[str]) -> bool:
        return bool(set(self.roles) & set(roles))

    def has_permission(self, permission: Permission) -> bool:
        return permission in permissions_for_roles(self.roles)
