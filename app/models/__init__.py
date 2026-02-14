"""Modelos SQLModel de Custodiam.

Importar aquí todos los modelos para que:
1. Alembic los detecte con --autogenerate
2. Se puedan importar desde un solo punto: `from app.models import Voluntario`
"""

from app.models.disponibilidad import Disponibilidad
from app.models.formacion import Formacion
from app.models.rol import Rol
from app.models.voluntario import EstadoVoluntario, Voluntario
from app.models.voluntario_rol import VoluntarioRol

__all__ = [
    "Disponibilidad",
    "EstadoVoluntario",
    "Formacion",
    "Rol",
    "Voluntario",
    "VoluntarioRol",
]
