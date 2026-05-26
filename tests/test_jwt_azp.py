"""Tests del check de Authorized Party (azp) en `_decode_token`.

Cubren la defensa en profundidad introducida en chore/audit-fixes (PR
#14): rechazar JWTs cuyo claim `azp` no coincida con el cliente
público esperado, incluso si la firma y el issuer son válidos.

Sin levantar Keycloak ni firmar tokens reales: mockeamos
`_jwks_client.get_signing_key_from_jwt` y `jwt.decode` directamente
para inyectar el payload exacto que queremos validar. Lo que se
testea es la lógica de `_decode_token` posterior al `jwt.decode`
estándar.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import app.core.security as security
from app.core.config import settings
from app.core.security import _decode_token


def _stub_token_decoding(monkeypatch, payload: dict) -> None:
    """Make `_decode_token` resolve any input token to `payload`.

    Patches the JWKS client to return a fake signing key, then
    short-circuits `jwt.decode` to skip the cryptographic check and
    return our payload directly. The `azp` validation that lives
    AFTER `jwt.decode` in `_decode_token` is what we want to exercise.
    """
    fake_signing_key = MagicMock(key="fake-key-for-tests")
    fake_jwks = MagicMock()
    fake_jwks.get_signing_key_from_jwt.return_value = fake_signing_key
    monkeypatch.setattr(security, "_jwks_client", fake_jwks)
    monkeypatch.setattr(
        security.jwt,
        "decode",
        lambda *args, **kwargs: payload,
    )


def _base_payload(**overrides) -> dict:
    """Minimal valid payload; tests pass keyword overrides."""
    base = {
        "sub": "test-user-id",
        "iss": settings.keycloak_issuer,
        "exp": 9_999_999_999,  # year 2286, comfortably non-expired
        "azp": settings.keycloak_authorized_party,
        "preferred_username": "testuser",
        "email": "test@custodiam.es",
        "given_name": "Test",
        "family_name": "User",
        "roles": ["voluntario"],
    }
    base.update(overrides)
    return base


def test_decode_token_accepts_correct_azp(monkeypatch):
    """`azp == settings.keycloak_authorized_party` -> payload returned as-is."""
    payload = _base_payload()
    _stub_token_decoding(monkeypatch, payload)

    result = _decode_token("dummy-token")

    assert result is payload


def test_decode_token_rejects_wrong_azp(monkeypatch):
    """`azp` from another client -> 401 with explanatory detail."""
    payload = _base_payload(azp="cliente-malicioso")
    _stub_token_decoding(monkeypatch, payload)

    with pytest.raises(HTTPException) as exc_info:
        _decode_token("dummy-token")

    assert exc_info.value.status_code == 401
    # Detail should name both the offending and the expected azp so
    # operations can diagnose the mismatch from logs alone.
    detail = str(exc_info.value.detail)
    assert "cliente-malicioso" in detail
    assert settings.keycloak_authorized_party in detail


def test_decode_token_rejects_missing_azp(monkeypatch):
    """Token without an `azp` claim -> 401, even if everything else is valid.

    Some malformed tokens (or tokens minted by edge OAuth tooling) may
    omit `azp` entirely. The check must reject them because
    `payload.get("azp")` returns None which cannot equal a configured
    string, but we make the assertion explicit so a future refactor
    that loosens the comparison doesn't silently weaken the gate.
    """
    payload = _base_payload()
    payload.pop("azp")
    _stub_token_decoding(monkeypatch, payload)

    with pytest.raises(HTTPException) as exc_info:
        _decode_token("dummy-token")

    assert exc_info.value.status_code == 401
    assert "None" in str(exc_info.value.detail)


def test_decode_token_respects_custom_authorized_party(monkeypatch):
    """If `Settings.keycloak_authorized_party` changes, the check follows.

    Locks in the contract that the expected `azp` is taken from
    settings and not hard-coded inside `_decode_token`. This is
    relevant for two future scenarios:
      * deploying the API behind a different public client_id
        (e.g. for a separate admin SPA);
      * test environments where the realm is shared with other apps
        that need to be rejected here.
    """
    monkeypatch.setattr(
        settings,
        "keycloak_authorized_party",
        "una-app-distinta",
    )

    # Token with the new expected azp -> ok.
    ok_payload = _base_payload(azp="una-app-distinta")
    _stub_token_decoding(monkeypatch, ok_payload)
    assert _decode_token("dummy-token") is ok_payload

    # Token with the previous default -> rejected, because the setting
    # is now pointing elsewhere.
    bad_payload = _base_payload(azp="custodiam-app")
    _stub_token_decoding(monkeypatch, bad_payload)
    with pytest.raises(HTTPException) as exc_info:
        _decode_token("dummy-token")
    assert exc_info.value.status_code == 401
    assert "una-app-distinta" in str(exc_info.value.detail)
