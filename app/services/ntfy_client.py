"""Cliente HTTP para ntfy (Epic E06 — canal de notificaciones redundante).

ntfy actúa como segundo canal cuando FCM falla o cuando el dispositivo
del voluntario está suscrito al topic correspondiente desde la propia
app de ntfy (vía deeplink en el caso de notificaciones críticas). El
protocolo es trivial: ``POST {base_url}/{topic}`` con el cuerpo del
mensaje en el body y los metadatos (título, prioridad, tags) en
headers.

Sigue el mismo patrón opt-in que :class:`KeycloakAdminClient` y
:class:`FcmAdminClient`: si ``ntfy_enabled`` es ``False``, todas las
operaciones devuelven ``None`` sin contactar con el servidor.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

import httpx

from app.core.config import settings
from app.models.notificacion import PrioridadNotificacion

logger = logging.getLogger(__name__)


class NtfyError(Exception):
    """El servidor ntfy devolvió un error o fue inalcanzable."""


# Mapeo Custodiam → ntfy. ntfy usa enteros del 1 (min) al 5 (max) y
# también acepta los strings nombrados.
_PRIORIDAD_A_NTFY: dict[PrioridadNotificacion, str] = {
    PrioridadNotificacion.CRITICA: "urgent",
    PrioridadNotificacion.ALTA: "high",
    PrioridadNotificacion.NORMAL: "default",
    PrioridadNotificacion.BAJA: "low",
}


class NtfyClient:
    """Cliente síncrono de ntfy.

    No mantiene estado: cada ``enviar`` es una request HTTP autocontenida.
    Si en el futuro hay topics con auth, este cliente añadirá un header
    ``Authorization`` configurable; en el alcance del MVP los topics son
    públicos.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        enabled: bool | None = None,
        default_topic: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base_url = (base_url or settings.ntfy_url).rstrip("/")
        self._enabled = (
            enabled if enabled is not None else settings.ntfy_enabled
        )
        self._default_topic = default_topic or settings.ntfy_default_topic
        self._http = http_client or httpx.Client(timeout=10.0)

    @property
    def enabled(self) -> bool:
        return bool(self._enabled) and bool(self._base_url)

    def enviar(
        self,
        *,
        titulo: str,
        cuerpo: str,
        prioridad: PrioridadNotificacion = PrioridadNotificacion.NORMAL,
        topic: str | None = None,
        tags: Iterable[str] | None = None,
    ) -> bool | None:
        """Publica un mensaje en un topic de ntfy.

        Devuelve ``True`` cuando ntfy acepta la publicación, ``None``
        cuando el cliente está deshabilitado, y lanza :class:`NtfyError`
        ante 5xx o errores de red.
        """

        if not self.enabled:
            logger.debug("NtfyClient deshabilitado: omitiendo enviar()")
            return None

        target_topic = topic or self._default_topic
        url = f"{self._base_url}/{target_topic}"

        headers: dict[str, str] = {
            "Title": titulo,
            "Priority": _PRIORIDAD_A_NTFY[prioridad],
        }
        if tags:
            headers["Tags"] = ",".join(tags)

        try:
            response = self._http.post(
                url,
                content=cuerpo.encode("utf-8"),
                headers=headers,
            )
        except httpx.HTTPError as e:
            raise NtfyError(f"Error de red al publicar en ntfy: {e}") from e

        if response.status_code == 200:
            return True
        if 500 <= response.status_code < 600:
            raise NtfyError(
                f"ntfy devolvió 5xx al publicar (HTTP {response.status_code}): "
                f"{response.text}"
            )
        raise NtfyError(
            f"Respuesta inesperada de ntfy (HTTP {response.status_code}): "
            f"{response.text}"
        )


# ---------------------------------------------------------------------------
# Dependency FastAPI
# ---------------------------------------------------------------------------


def get_ntfy_client() -> NtfyClient:
    """Factoría inyectable como `Depends` en routers."""

    return NtfyClient()
