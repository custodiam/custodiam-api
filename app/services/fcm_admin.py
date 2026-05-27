"""Cliente HTTP para la API HTTP v1 de Firebase Cloud Messaging (Epic E06).

Sigue el mismo patrón opt-in que :class:`KeycloakAdminClient`: si la
cuenta de servicio de Google no está configurada, todas las operaciones
de envío devuelven ``None`` sin contactar con FCM. Esto permite arrancar
la API y ejecutar los tests sin necesitar credenciales reales.

Flujo de autenticación
----------------------

FCM HTTP v1 exige OAuth 2.0 con un access token derivado de la cuenta
de servicio de Google (la legacy server key fue deprecada el
20-jun-2024). El flujo se resume en:

1. Firmar un JWT RS256 con la ``private_key`` del JSON, ``iss`` =
   ``client_email``, ``aud`` = endpoint de token, ``scope`` =
   ``firebase.messaging``.
2. Intercambiarlo en ``https://oauth2.googleapis.com/token`` por un
   access token (grant ``urn:ietf:params:oauth:grant-type:jwt-bearer``).
3. Usar el access token como ``Authorization: Bearer ...`` contra el
   endpoint de envío.

El token se cachea con un margen de seguridad antes de expirar y se
renueva bajo demanda — réplica fiel del patrón de
:class:`KeycloakAdminClient`.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from app.core.config import settings
from app.models.notificacion import PrioridadNotificacion

logger = logging.getLogger(__name__)


GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
FCM_MESSAGES_ENDPOINT = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


class FcmAdminError(Exception):
    """El backend de FCM devolvió un error 5xx o fue inalcanzable."""


class FcmAdminClient:
    """Cliente síncrono de FCM HTTP v1.

    Métodos públicos:

    - :attr:`enabled` — ``True`` si hay credenciales cargadas.
    - :meth:`enviar` — manda un push a un único token. Devuelve ``True``
      si FCM lo aceptó, ``False`` si el token está desregistrado o es
      inválido (señal para que el caller marque el ``Dispositivo`` como
      ``activo=False``). Cualquier 5xx levanta :class:`FcmAdminError`.
    """

    _TOKEN_REFRESH_MARGIN_SECONDS: float = 30.0

    def __init__(
        self,
        *,
        service_account_json_path: str | None = None,
        project_id: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._service_account_path = (
            service_account_json_path
            if service_account_json_path is not None
            else settings.fcm_service_account_json_path
        )
        self._project_id = project_id or settings.fcm_project_id
        self._http = http_client or httpx.Client(timeout=10.0)

        self._service_account: dict[str, Any] | None = None
        self._private_key: Any | None = None
        self._access_token: str | None = None
        self._access_token_expires_at: float = 0.0

        # Carga perezosa del JSON: solo si el cliente está habilitado,
        # para que el modo deshabilitado no necesite el archivo en disco.
        if self.enabled:
            self._load_service_account()

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """``True`` si hay credenciales y project_id configurados."""

        return bool(self._service_account_path) and bool(self._project_id)

    # ------------------------------------------------------------------
    # Carga del service account y obtención del access token
    # ------------------------------------------------------------------

    def _load_service_account(self) -> None:
        try:
            raw = Path(self._service_account_path).read_text(encoding="utf-8")
        except OSError as e:
            raise FcmAdminError(
                f"No se pudo leer la cuenta de servicio de FCM en "
                f"{self._service_account_path!r}: {e}"
            ) from e

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise FcmAdminError(
                f"La cuenta de servicio FCM no es un JSON válido: {e}"
            ) from e

        if "private_key" not in data or "client_email" not in data:
            raise FcmAdminError(
                "La cuenta de servicio FCM no contiene los campos "
                "`private_key` y `client_email` requeridos"
            )

        try:
            self._private_key = load_pem_private_key(
                data["private_key"].encode("utf-8"),
                password=None,
            )
        except ValueError as e:
            raise FcmAdminError(
                f"La `private_key` de la cuenta de servicio no es PEM válido: {e}"
            ) from e

        self._service_account = data

    def _get_access_token(self) -> str:
        """Devuelve un access token de Google, renovándolo si está caducado."""

        now = time.monotonic()
        if (
            self._access_token
            and now < self._access_token_expires_at - self._TOKEN_REFRESH_MARGIN_SECONDS
        ):
            return self._access_token

        assert self._service_account is not None
        assert self._private_key is not None

        epoch_now = int(time.time())
        assertion_payload = {
            "iss": self._service_account["client_email"],
            "scope": FCM_SCOPE,
            "aud": GOOGLE_TOKEN_URL,
            "iat": epoch_now,
            "exp": epoch_now + 3600,
        }
        assertion = jwt.encode(
            assertion_payload, self._private_key, algorithm="RS256"
        )

        try:
            response = self._http.post(
                GOOGLE_TOKEN_URL,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
            )
        except httpx.HTTPError as e:
            raise FcmAdminError(
                f"No se pudo contactar con Google OAuth para obtener el token de FCM: {e}"
            ) from e

        if response.status_code != 200:
            raise FcmAdminError(
                f"Google rechazó el intercambio de JWT por access token "
                f"(HTTP {response.status_code}): {response.text}"
            )

        payload = response.json()
        access_token = payload.get("access_token")
        expires_in = float(payload.get("expires_in", 3600))
        if not access_token:
            raise FcmAdminError(
                "La respuesta de Google OAuth no contenía `access_token`"
            )

        self._access_token = access_token
        self._access_token_expires_at = now + expires_in
        return access_token

    # ------------------------------------------------------------------
    # Envío
    # ------------------------------------------------------------------

    def enviar(
        self,
        *,
        token: str,
        titulo: str,
        cuerpo: str,
        prioridad: PrioridadNotificacion = PrioridadNotificacion.NORMAL,
        data: dict[str, str] | None = None,
    ) -> bool | None:
        """Manda un push a un token FCM.

        Devoluciones posibles:

        - ``True`` si FCM aceptó el mensaje (HTTP 200).
        - ``False`` si el token no es válido (HTTP 404 / ``UNREGISTERED``
          / ``INVALID_ARGUMENT``). Señal para el caller de que conviene
          marcar el ``Dispositivo`` como ``activo=False``.
        - ``None`` si el cliente está deshabilitado.

        Lanza :class:`FcmAdminError` ante errores transitorios (5xx o
        de red) para que el caller decida si reintenta o registra el
        fallo en el audit log y continúa.
        """

        if not self.enabled:
            logger.debug("FcmAdminClient deshabilitado: omitiendo enviar()")
            return None

        access_token = self._get_access_token()
        url = FCM_MESSAGES_ENDPOINT.format(project_id=self._project_id)
        body = self._construir_mensaje(
            token=token,
            titulo=titulo,
            cuerpo=cuerpo,
            prioridad=prioridad,
            data=data,
        )

        try:
            response = self._http.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.HTTPError as e:
            raise FcmAdminError(
                f"Error de red al enviar push a FCM: {e}"
            ) from e

        if response.status_code == 200:
            return True
        # 400 con error.status=INVALID_ARGUMENT y 404 con UNREGISTERED son
        # los códigos canónicos de "este token ya no sirve" de la API v1.
        if response.status_code in (400, 404):
            return False
        if 500 <= response.status_code < 600:
            raise FcmAdminError(
                f"FCM devolvió 5xx al enviar push (HTTP {response.status_code}): "
                f"{response.text}"
            )
        raise FcmAdminError(
            f"Respuesta inesperada de FCM (HTTP {response.status_code}): "
            f"{response.text}"
        )

    @staticmethod
    def _construir_mensaje(
        *,
        token: str,
        titulo: str,
        cuerpo: str,
        prioridad: PrioridadNotificacion,
        data: dict[str, str] | None,
    ) -> dict[str, Any]:
        """Construye el JSON del request de FCM HTTP v1.

        Mapea :class:`PrioridadNotificacion` al campo ``android.priority``
        y al header ``apns-priority`` para iOS. ``critica`` y ``alta``
        son ``HIGH``/``10``; ``normal`` y ``baja`` son ``NORMAL``/``5``.
        """

        es_alta = prioridad in (
            PrioridadNotificacion.CRITICA,
            PrioridadNotificacion.ALTA,
        )
        mensaje: dict[str, Any] = {
            "message": {
                "token": token,
                "notification": {"title": titulo, "body": cuerpo},
                "android": {"priority": "HIGH" if es_alta else "NORMAL"},
                "apns": {
                    "headers": {"apns-priority": "10" if es_alta else "5"}
                },
            }
        }
        if data:
            # FCM exige que los valores del campo `data` sean strings.
            mensaje["message"]["data"] = {k: str(v) for k, v in data.items()}
        return mensaje


# ---------------------------------------------------------------------------
# Dependency FastAPI
# ---------------------------------------------------------------------------


def get_fcm_admin() -> FcmAdminClient:
    """Factoría inyectable como `Depends` en routers."""

    return FcmAdminClient()
