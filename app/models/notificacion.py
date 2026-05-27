"""Modelo de Notificacion (Epic E06).

Audit log de las notificaciones disparadas por el backend. Cada fila
representa un "evento de notificación" (p. ej. "se convocó al servicio
X"); los envíos por canal (FCM, ntfy) se contabilizan agregados en
``enviadas_count`` y ``entregadas_count`` para no inflar la tabla con
una fila por token.

Decisiones de modelado:

- ``servicio_id`` es nullable: hay notificaciones que no cuelgan de un
  servicio (avisos del sistema, recordatorios genéricos).
- ``tipo`` y ``prioridad`` son enums cerrados; la prioridad se mapea al
  campo nativo de FCM (``android.priority`` y ``apns-priority``) y al
  header ``Priority`` de ntfy.
- ``enviadas_count`` cuenta los pushes lanzados; ``entregadas_count`` se
  reserva para confirmaciones de entrega cuando el backend lo soporte
  (FCM no expone delivery receipts gratuitos, así que en el MVP queda
  en 0 salvo que se complete con webhooks de ntfy o BigQuery).
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import created_at_column, pk_uuid

if TYPE_CHECKING:
    from app.models.servicio import Servicio


class TipoNotificacion(enum.StrEnum):
    """Categoría funcional de la notificación."""

    EMERGENCIA = "emergencia"
    SERVICIO = "servicio"
    RECORDATORIO = "recordatorio"
    SISTEMA = "sistema"


class PrioridadNotificacion(enum.StrEnum):
    """Prioridad de entrega, mapeada al canal del SO destino."""

    CRITICA = "critica"
    ALTA = "alta"
    NORMAL = "normal"
    BAJA = "baja"


class Notificacion(SQLModel, table=True):
    """Registro de auditoría de cada notificación emitida."""

    __tablename__ = "notificaciones"

    id: uuid.UUID = pk_uuid()
    servicio_id: uuid.UUID | None = Field(
        default=None, foreign_key="servicios.id", index=True
    )

    titulo: str = Field(max_length=255)
    cuerpo: str = Field(max_length=2000)

    tipo: TipoNotificacion = Field(
        sa_column=Column(
            SAEnum(
                TipoNotificacion,
                name="tipo_notificacion",
                create_constraint=True,
            ),
            nullable=False,
        ),
    )
    prioridad: PrioridadNotificacion = Field(
        sa_column=Column(
            SAEnum(
                PrioridadNotificacion,
                name="prioridad_notificacion",
                create_constraint=True,
            ),
            nullable=False,
        ),
    )

    enviada_at: datetime | None = created_at_column()
    enviadas_count: int = Field(default=0, ge=0, nullable=False)
    entregadas_count: int = Field(default=0, ge=0, nullable=False)

    servicio: Optional["Servicio"] = Relationship()

    def __repr__(self) -> str:
        return (
            f"<Notificacion {self.tipo.value}/{self.prioridad.value} "
            f"{self.titulo!r} enviadas={self.enviadas_count}>"
        )
