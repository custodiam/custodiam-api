"""Schemas Pydantic para Dispositivo (Epic E06 — Notificaciones).

Cubren los endpoints REST de gestión de tokens FCM por el propio
voluntario (US-06-04, EN-06-05 del backlog):

- ``POST /dispositivos`` — registrar/refrescar mi token (idempotente).
- ``GET /dispositivos/me`` — listar mis dispositivos activos.
- ``DELETE /dispositivos/{id}`` — dar de baja un dispositivo propio.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.dispositivo import PlataformaDispositivo


class DispositivoRegistrar(BaseModel):
    """Body del POST /dispositivos.

    El backend resuelve el voluntario destinatario a partir del JWT
    (``sub`` → ``keycloak_id``), por lo que el cliente NO envía el
    ``voluntario_id``. Reduce superficie de ataque (un cliente
    autenticado no puede registrar tokens en nombre de otro usuario).
    """

    fcm_token: str = Field(min_length=1, max_length=512)
    plataforma: PlataformaDispositivo


class DispositivoResponse(BaseModel):
    """Schema de respuesta de un dispositivo registrado."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    voluntario_id: UUID
    fcm_token: str
    plataforma: PlataformaDispositivo
    activo: bool
    created_at: datetime | None = None
    ultima_actualizacion: datetime | None = None
