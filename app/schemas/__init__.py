"""Schemas Pydantic de Custodiam.

Convivencia con `app.models` (SQLModel `table=True`): los modelos viven
en `app.models` y se usan como tablas; los schemas Pydantic puros viven
aquí y se usan en endpoints REST para validación de entrada y forma de
respuesta. La elección de NO usar `SQLModel(table=False)` como schema
de API se mantiene por flexibilidad (un endpoint puede combinar campos
de varios modelos).
"""

from app.schemas.acreditacion import (
    AcreditacionBase,
    AcreditacionCreate,
    AcreditacionResponse,
    AcreditacionUpdate,
    TipoAcreditacionResponse,
)
from app.schemas.auth import CurrentUser
from app.schemas.contacto_emergencia import (
    ContactoEmergenciaBase,
    ContactoEmergenciaCreate,
    ContactoEmergenciaResponse,
    ContactoEmergenciaUpdate,
)
from app.schemas.equipamiento import (
    TallaVoluntarioBase,
    TallaVoluntarioCreate,
    TallaVoluntarioResponse,
    TallaVoluntarioUpdate,
    TipoEquipamientoResponse,
)
from app.schemas.fichaje import (
    FichajeEnServicioResponse,
    FichajeResponse,
    HorasAcumuladasResponse,
)
from app.schemas.servicio import (
    InscripcionServicioResponse,
    ServicioBase,
    ServicioCerrar,
    ServicioConvocar,
    ServicioCreate,
    ServicioResponse,
    ServicioSummary,
    ServicioUpdate,
    VoluntarioInscritoResponse,
)
from app.schemas.voluntario import (
    VoluntarioBase,
    VoluntarioCreate,
    VoluntarioResponse,
    VoluntarioSummary,
    VoluntarioUpdateAdmin,
    VoluntarioUpdateSelf,
)

__all__ = [
    "AcreditacionBase",
    "AcreditacionCreate",
    "AcreditacionResponse",
    "AcreditacionUpdate",
    "ContactoEmergenciaBase",
    "ContactoEmergenciaCreate",
    "ContactoEmergenciaResponse",
    "ContactoEmergenciaUpdate",
    "CurrentUser",
    "FichajeEnServicioResponse",
    "FichajeResponse",
    "HorasAcumuladasResponse",
    "InscripcionServicioResponse",
    "ServicioBase",
    "ServicioCerrar",
    "ServicioConvocar",
    "ServicioCreate",
    "ServicioResponse",
    "ServicioSummary",
    "ServicioUpdate",
    "TallaVoluntarioBase",
    "TallaVoluntarioCreate",
    "TallaVoluntarioResponse",
    "TallaVoluntarioUpdate",
    "TipoAcreditacionResponse",
    "TipoEquipamientoResponse",
    "VoluntarioBase",
    "VoluntarioCreate",
    "VoluntarioInscritoResponse",
    "VoluntarioResponse",
    "VoluntarioSummary",
    "VoluntarioUpdateAdmin",
    "VoluntarioUpdateSelf",
]
