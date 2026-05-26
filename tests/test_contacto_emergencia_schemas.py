"""Tests de schemas Pydantic de ContactoEmergencia (EN-02-01, ADR-025)."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas import (
    ContactoEmergenciaCreate,
    ContactoEmergenciaResponse,
    ContactoEmergenciaUpdate,
)


class TestContactoEmergenciaCreate:
    """POST `/voluntarios/{id}/contactos-emergencia`."""

    def test_primer_contacto(self):
        contacto = ContactoEmergenciaCreate(
            nombre="María García",
            telefono="+34666123456",
            parentesco="madre",
            orden_preferencia=1,
        )
        assert contacto.nombre == "María García"
        assert contacto.parentesco == "madre"
        assert contacto.orden_preferencia == 1

    def test_contacto_sin_parentesco(self):
        """`parentesco` es opcional (texto libre)."""
        contacto = ContactoEmergenciaCreate(
            nombre="Carlos",
            telefono="+34666123456",
        )
        assert contacto.parentesco is None
        # Default orden_preferencia = 1
        assert contacto.orden_preferencia == 1

    def test_segundo_contacto(self):
        contacto = ContactoEmergenciaCreate(
            nombre="Pedro",
            telefono="+34666987654",
            parentesco="amigo cercano",
            orden_preferencia=2,
        )
        assert contacto.orden_preferencia == 2

    def test_falta_nombre(self):
        with pytest.raises(ValidationError) as exc:
            ContactoEmergenciaCreate(telefono="+34666123456")
        assert any(e["loc"] == ("nombre",) for e in exc.value.errors())

    def test_falta_telefono(self):
        with pytest.raises(ValidationError) as exc:
            ContactoEmergenciaCreate(nombre="María")
        assert any(e["loc"] == ("telefono",) for e in exc.value.errors())

    def test_orden_preferencia_fuera_de_rango_bajo(self):
        with pytest.raises(ValidationError) as exc:
            ContactoEmergenciaCreate(
                nombre="María",
                telefono="+34666123456",
                orden_preferencia=0,
            )
        assert any(e["loc"] == ("orden_preferencia",) for e in exc.value.errors())

    def test_orden_preferencia_fuera_de_rango_alto(self):
        """Cap a 10 contactos máximo por voluntario."""
        with pytest.raises(ValidationError):
            ContactoEmergenciaCreate(
                nombre="María",
                telefono="+34666123456",
                orden_preferencia=11,
            )

    def test_nombre_demasiado_largo(self):
        with pytest.raises(ValidationError):
            ContactoEmergenciaCreate(
                nombre="X" * 256,
                telefono="+34666123456",
            )

    def test_parentesco_libre(self):
        """`parentesco` es texto libre — no se restringe a un catálogo."""
        contacto = ContactoEmergenciaCreate(
            nombre="Roberto",
            telefono="+34666123456",
            parentesco="compañero de piso desde hace 3 años",
        )
        assert "compañero" in contacto.parentesco


class TestContactoEmergenciaUpdate:
    """PATCH — todos los campos opcionales."""

    def test_update_telefono(self):
        update = ContactoEmergenciaUpdate(telefono="+34611111111")
        assert update.telefono == "+34611111111"
        assert update.nombre is None

    def test_update_orden(self):
        """Promover un contacto a primera posición."""
        update = ContactoEmergenciaUpdate(orden_preferencia=1)
        assert update.orden_preferencia == 1


class TestContactoEmergenciaResponse:
    """Respuesta GET."""

    def test_response_con_id(self):
        contacto_id = uuid4()
        voluntario_id = uuid4()
        response = ContactoEmergenciaResponse(
            id=contacto_id,
            voluntario_id=voluntario_id,
            nombre="María García",
            telefono="+34666123456",
            parentesco="madre",
            orden_preferencia=1,
        )
        assert response.id == contacto_id
        assert response.voluntario_id == voluntario_id
