"""Modelos SQLModel de Custodiam.

Importar aquí todos los modelos para que:
1. Alembic los detecte con --autogenerate
2. Se puedan importar desde un solo punto: `from app.models import Voluntario`
"""

from app.models.acreditacion import Acreditacion
from app.models.asignacion_material import AsignacionMaterial, TipoAsignacion
from app.models.asignacion_vehiculo import AsignacionVehiculo
from app.models.contacto_emergencia import ContactoEmergencia
from app.models.disponibilidad import Disponibilidad
from app.models.fichaje import Fichaje
from app.models.inscripcion_servicio import InscripcionServicio, TipoInscripcion
from app.models.material import EstadoInventario, Material, TipoMaterial
from app.models.rol import Rol
from app.models.servicio import EstadoServicio, Servicio, TipoServicio
from app.models.talla_voluntario import TallaVoluntario
from app.models.tipo_acreditacion import (
    CategoriaAcreditacion,
    TipoAcreditacion,
)
from app.models.tipo_equipamiento import TipoEquipamiento
from app.models.vehiculo import TipoVehiculo, Vehiculo
from app.models.voluntario import EstadoVoluntario, Voluntario
from app.models.voluntario_rol import VoluntarioRol

__all__ = [
    "Acreditacion",
    "AsignacionMaterial",
    "AsignacionVehiculo",
    "CategoriaAcreditacion",
    "ContactoEmergencia",
    "Disponibilidad",
    "EstadoInventario",
    "EstadoServicio",
    "EstadoVoluntario",
    "Fichaje",
    "InscripcionServicio",
    "Material",
    "Rol",
    "Servicio",
    "TallaVoluntario",
    "TipoAcreditacion",
    "TipoAsignacion",
    "TipoEquipamiento",
    "TipoInscripcion",
    "TipoMaterial",
    "TipoServicio",
    "TipoVehiculo",
    "Vehiculo",
    "Voluntario",
    "VoluntarioRol",
]
