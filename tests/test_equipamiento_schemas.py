"""Tests de schemas Pydantic de Equipamiento + TallaVoluntario (EN-02-01)."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas import (
    TallaVoluntarioCreate,
    TallaVoluntarioResponse,
    TallaVoluntarioUpdate,
    TipoEquipamientoResponse,
)


class TestTallaVoluntarioCreate:
    """POST `/voluntarios/{id}/tallas`."""

    def test_talla_camisa(self):
        talla = TallaVoluntarioCreate(tipo_id=uuid4(), valor="M")
        assert talla.valor == "M"

    def test_talla_pantalon_numerica(self):
        talla = TallaVoluntarioCreate(tipo_id=uuid4(), valor="42")
        assert talla.valor == "42"

    def test_falta_tipo_id(self):
        with pytest.raises(ValidationError) as exc:
            TallaVoluntarioCreate(valor="M")
        assert any(e["loc"] == ("tipo_id",) for e in exc.value.errors())

    def test_falta_valor(self):
        with pytest.raises(ValidationError) as exc:
            TallaVoluntarioCreate(tipo_id=uuid4())
        assert any(e["loc"] == ("valor",) for e in exc.value.errors())

    def test_valor_demasiado_largo(self):
        with pytest.raises(ValidationError):
            TallaVoluntarioCreate(tipo_id=uuid4(), valor="X" * 21)


class TestTallaVoluntarioUpdate:
    """PATCH `/tallas/{id}` — solo el valor se actualiza."""

    def test_update_valor(self):
        update = TallaVoluntarioUpdate(valor="L")
        assert update.valor == "L"

    def test_update_no_permite_cambiar_tipo(self):
        """La actualización no debe permitir cambiar el `tipo_id`.

        Si quieres cambiar el tipo de equipamiento, borras la talla
        actual y creas una nueva. Esto preserva el constraint UNIQUE
        (voluntario, tipo).
        """
        assert "tipo_id" not in TallaVoluntarioUpdate.model_fields


class TestTallaVoluntarioResponse:
    """Respuesta GET con tipo expandido."""

    def test_response_con_tipo_expandido(self):
        tipo = TipoEquipamientoResponse(
            id=uuid4(),
            codigo="BOTAS",
            nombre="Botas",
            sistema_tallas="36-50",
            activo=True,
        )
        response = TallaVoluntarioResponse(
            id=uuid4(),
            voluntario_id=uuid4(),
            tipo_id=tipo.id,
            valor="42",
            tipo=tipo,
        )
        assert response.tipo.codigo == "BOTAS"
        assert response.tipo.sistema_tallas == "36-50"


class TestTipoEquipamientoResponse:
    """Catálogo (solo lectura)."""

    def test_tipo_sin_sistema_tallas(self):
        tipo = TipoEquipamientoResponse(
            id=uuid4(),
            codigo="GUANTES",
            nombre="Guantes",
            activo=True,
        )
        assert tipo.sistema_tallas is None
