"""Tests de schemas Pydantic de Voluntario (EN-02-01, ADR-025)."""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.voluntario import EstadoVoluntario
from app.schemas import (
    VoluntarioCreate,
    VoluntarioResponse,
    VoluntarioSummary,
    VoluntarioUpdateAdmin,
    VoluntarioUpdateSelf,
)


class TestVoluntarioCreate:
    """POST `/voluntarios` (alta admin, CU-10)."""

    def test_alta_con_campos_obligatorios_minimos(self):
        v = VoluntarioCreate(
            nombre="Ana García",
            telefono="+34666123456",
            municipio="Zaragoza",
            fecha_nacimiento=date(1990, 5, 12),
            email="ana@example.com",
        )
        assert v.nombre == "Ana García"
        assert v.municipio == "Zaragoza"
        assert v.email == "ana@example.com"
        assert v.conductor_habilitado is False  # default

    def test_alta_sin_email_falla(self):
        # Email es obligatorio en el alta (es la llave del onboarding).
        with pytest.raises(ValidationError) as exc:
            VoluntarioCreate(
                nombre="Ana García",
                telefono="+34666123456",
                municipio="Zaragoza",
                fecha_nacimiento=date(1990, 5, 12),
            )
        assert any(e["loc"] == ("email",) for e in exc.value.errors())

    def test_fecha_nacimiento_futura_falla(self):
        with pytest.raises(ValidationError) as exc:
            VoluntarioCreate(
                nombre="Ana García",
                telefono="+34666123456",
                municipio="Zaragoza",
                fecha_nacimiento=date.today() + timedelta(days=1),
                email="ana@example.com",
            )
        assert any(e["loc"] == ("fecha_nacimiento",) for e in exc.value.errors())

    def test_alta_con_todos_los_opcionales(self):
        v = VoluntarioCreate(
            nombre="Ana García",
            telefono="+34666123456",
            municipio="Zaragoza",
            fecha_nacimiento=date(1990, 5, 12),
            dni="12345678Z",
            email="ana@example.com",
            direccion="Calle Mayor 1",
            foto_url="https://example.com/foto.jpg",
            conductor_habilitado=True,
        )
        assert v.email == "ana@example.com"
        assert v.dni == "12345678Z"
        assert v.conductor_habilitado is True

    def test_falta_nombre_obligatorio(self):
        with pytest.raises(ValidationError) as exc:
            VoluntarioCreate(
                telefono="+34666123456",
                municipio="Zaragoza",
                fecha_nacimiento=date(1990, 5, 12),
            )
        assert any(e["loc"] == ("nombre",) for e in exc.value.errors())

    def test_falta_telefono_obligatorio(self):
        with pytest.raises(ValidationError) as exc:
            VoluntarioCreate(
                nombre="Ana",
                municipio="Zaragoza",
                fecha_nacimiento=date(1990, 5, 12),
            )
        assert any(e["loc"] == ("telefono",) for e in exc.value.errors())

    def test_falta_municipio_obligatorio(self):
        with pytest.raises(ValidationError) as exc:
            VoluntarioCreate(
                nombre="Ana",
                telefono="+34666123456",
                fecha_nacimiento=date(1990, 5, 12),
            )
        assert any(e["loc"] == ("municipio",) for e in exc.value.errors())

    def test_falta_fecha_nacimiento_obligatorio(self):
        with pytest.raises(ValidationError) as exc:
            VoluntarioCreate(
                nombre="Ana",
                telefono="+34666123456",
                municipio="Zaragoza",
            )
        assert any(e["loc"] == ("fecha_nacimiento",) for e in exc.value.errors())

    def test_email_invalido_falla(self):
        with pytest.raises(ValidationError) as exc:
            VoluntarioCreate(
                nombre="Ana",
                telefono="+34666123456",
                municipio="Zaragoza",
                fecha_nacimiento=date(1990, 5, 12),
                email="no-es-un-email",
            )
        assert any(e["loc"] == ("email",) for e in exc.value.errors())

    def test_nombre_demasiado_largo_falla(self):
        with pytest.raises(ValidationError):
            VoluntarioCreate(
                nombre="X" * 256,
                telefono="+34666123456",
                municipio="Zaragoza",
                fecha_nacimiento=date(1990, 5, 12),
            )


class TestVoluntarioUpdateAdmin:
    """PATCH admin (CU-11 B) — todos los campos opcionales."""

    def test_update_solo_un_campo(self):
        update = VoluntarioUpdateAdmin(telefono="+34666999888")
        assert update.telefono == "+34666999888"
        assert update.nombre is None
        assert update.email is None

    def test_update_estado_a_baja(self):
        update = VoluntarioUpdateAdmin(estado=EstadoVoluntario.BAJA, fecha_baja=date.today())
        assert update.estado == EstadoVoluntario.BAJA
        assert update.fecha_baja == date.today()

    def test_update_vacio_es_valido(self):
        """Un PATCH puede no traer ningún campo — el servicio lo manejará."""
        update = VoluntarioUpdateAdmin()
        assert update.nombre is None


class TestVoluntarioUpdateSelf:
    """PATCH self (CU-11 A) — solo datos de contacto.

    El schema NO incluye campos restringidos (nombre, dni, rol, estado).
    Esto refuerza el corte a nivel de schema, no solo a nivel endpoint.
    """

    def test_update_telefono_propio(self):
        update = VoluntarioUpdateSelf(telefono="+34611111111")
        assert update.telefono == "+34611111111"

    def test_update_email_propio(self):
        update = VoluntarioUpdateSelf(email="nuevo@example.com")
        assert update.email == "nuevo@example.com"

    def test_self_schema_no_permite_nombre(self):
        """El schema VoluntarioUpdateSelf no debe tener el campo `nombre`."""
        # Pydantic v2 acepta campos extra por defecto si no se configuró
        # `model_config = ConfigDict(extra="forbid")`. Aquí verificamos
        # que el campo NO está en model_fields, lo que es señal segura
        # para el endpoint: solo lee los campos declarados, ignora extras.
        assert "nombre" not in VoluntarioUpdateSelf.model_fields
        assert "dni" not in VoluntarioUpdateSelf.model_fields
        assert "estado" not in VoluntarioUpdateSelf.model_fields
        assert "fecha_alta" not in VoluntarioUpdateSelf.model_fields
        assert "fecha_baja" not in VoluntarioUpdateSelf.model_fields


class TestVoluntarioResponse:
    """Respuesta GET — incluye id + timestamps + relaciones nested."""

    def test_response_con_listas_vacias(self):
        voluntario_id = uuid4()
        response = VoluntarioResponse(
            id=voluntario_id,
            nombre="Ana",
            telefono="+34666123456",
            municipio="Zaragoza",
            fecha_nacimiento=date(1990, 5, 12),
            estado=EstadoVoluntario.ACTIVO,
            fecha_alta=date.today(),
        )
        assert response.id == voluntario_id
        assert response.acreditaciones == []
        assert response.tallas == []
        assert response.contactos_emergencia == []


class TestVoluntarioSummary:
    """Schema compacto para listas paginadas (CU-15)."""

    def test_summary_campos_minimos(self):
        summary = VoluntarioSummary(
            id=uuid4(),
            nombre="Ana",
            telefono="+34666123456",
            municipio="Zaragoza",
            estado=EstadoVoluntario.ACTIVO,
            conductor_habilitado=False,
        )
        assert summary.nombre == "Ana"
        # Summary no debe incluir relaciones (es para listas, performance).
        assert "acreditaciones" not in VoluntarioSummary.model_fields
        assert "tallas" not in VoluntarioSummary.model_fields
