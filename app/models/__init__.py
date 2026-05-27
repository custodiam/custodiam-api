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
from app.models.dispositivo import Dispositivo, PlataformaDispositivo
from app.models.fichaje import Fichaje
from app.models.inscripcion_servicio import InscripcionServicio, TipoInscripcion
from app.models.material import EstadoInventario, Material, TipoMaterial
from app.models.notificacion import (
    Notificacion,
    PrioridadNotificacion,
    TipoNotificacion,
)
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
from app.models.voluntario_evento import TipoEventoVoluntario, VoluntarioEvento
from app.models.voluntario_rol import VoluntarioRol

__all__ = [
    "Acreditacion",
    "AsignacionMaterial",
    "AsignacionVehiculo",
    "CategoriaAcreditacion",
    "ContactoEmergencia",
    "Disponibilidad",
    "Dispositivo",
    "EstadoInventario",
    "EstadoServicio",
    "EstadoVoluntario",
    "Fichaje",
    "InscripcionServicio",
    "Material",
    "Notificacion",
    "PlataformaDispositivo",
    "PrioridadNotificacion",
    "Rol",
    "Servicio",
    "TallaVoluntario",
    "TipoAcreditacion",
    "TipoAsignacion",
    "TipoEquipamiento",
    "TipoEventoVoluntario",
    "TipoInscripcion",
    "TipoMaterial",
    "TipoNotificacion",
    "TipoServicio",
    "TipoVehiculo",
    "Vehiculo",
    "Voluntario",
    "VoluntarioEvento",
    "VoluntarioRol",
]
