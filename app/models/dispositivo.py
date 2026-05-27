"""Modelo de Dispositivo (Epic E06 — Notificaciones).

Almacena los tokens FCM emitidos por las apps móviles y web de los
voluntarios, con su plataforma y un flag operativo ``activo``. El
backend usa estas filas para resolver "a quién enviar push" cuando un
mando convoca un servicio (CU-03) o cuando se publica una emergencia.

Decisiones de modelado:

- ``fcm_token`` es UNIQUE: el mismo token nunca pertenece a dos
  voluntarios a la vez. Si la app se reloguea con otra cuenta, el POST
  idempotente del endpoint reasigna el token al voluntario actual y
  marca como ``activo=False`` cualquier vinculación previa.
- ``activo`` permite soft delete: si el voluntario se da de baja o
  invalida el token desde la app, el registro se conserva con
  ``activo=False`` para preservar historial de envíos. El cleanup físico
  vive en un enabler operativo posterior (cuando el volumen lo exija).
- ``ultima_actualizacion`` (nombre literal del backlog) usa el patrón
  ``updated_at_column()`` compartido: server_default + onupdate now().
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import created_at_column, pk_uuid, updated_at_column

if TYPE_CHECKING:
    from app.models.voluntario import Voluntario


class PlataformaDispositivo(enum.StrEnum):
    """Plataforma desde la que se obtuvo el token FCM."""

    ANDROID = "android"
    IOS = "ios"
    WEB = "web"


class Dispositivo(SQLModel, table=True):
    """Dispositivo registrado para recibir notificaciones push."""

    __tablename__ = "dispositivos"

    id: uuid.UUID = pk_uuid()
    voluntario_id: uuid.UUID = Field(foreign_key="voluntarios.id", index=True)
    fcm_token: str = Field(max_length=512, unique=True, index=True)
    plataforma: PlataformaDispositivo = Field(
        sa_column=Column(
            SAEnum(
                PlataformaDispositivo,
                name="plataforma_dispositivo",
                create_constraint=True,
            ),
            nullable=False,
        ),
    )
    activo: bool = Field(default=True, nullable=False)

    created_at: datetime | None = created_at_column()
    ultima_actualizacion: datetime | None = updated_at_column()

    voluntario: Optional["Voluntario"] = Relationship()

    def __repr__(self) -> str:
        marca = "on" if self.activo else "off"
        return (
            f"<Dispositivo {self.plataforma.value} "
            f"voluntario={self.voluntario_id} {marca}>"
        )
