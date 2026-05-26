"""Tests de schemas Pydantic de Acreditacion (EN-02-01, ADR-025)."""

from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.tipo_acreditacion import CategoriaAcreditacion
from app.schemas import (
    AcreditacionCreate,
    AcreditacionResponse,
    AcreditacionUpdate,
    TipoAcreditacionResponse,
)


class TestAcreditacionCreate:
    """POST `/voluntarios/{id}/acreditaciones`."""

    def test_carnet_conducir_minimo(self):
        """Carnet con solo los campos obligatorios."""
        tipo_id = uuid4()
        acred = AcreditacionCreate(
            tipo_id=tipo_id,
            categoria=CategoriaAcreditacion.LICENCIA_OFICIAL,
            fecha_obtencion=date(2020, 6, 15),
        )
        assert acred.tipo_id == tipo_id
        assert acred.categoria == CategoriaAcreditacion.LICENCIA_OFICIAL
        assert acred.fecha_caducidad is None
        assert acred.numero is None
        assert acred.datos_especificos is None

    def test_carnet_conducir_completo_con_datos_especificos(self):
        """Carnet con datos_especificos JSONB (tipo, incluye_remolque)."""
        acred = AcreditacionCreate(
            tipo_id=uuid4(),
            categoria=CategoriaAcreditacion.LICENCIA_OFICIAL,
            fecha_obtencion=date(2020, 6, 15),
            fecha_caducidad=date(2030, 6, 15),
            numero="12345678Z-B",
            entidad_emisora="DGT",
            datos_especificos={"tipo": "B", "incluye_remolque": False},
            documento_url="https://example.com/carnet.pdf",
        )
        assert acred.datos_especificos["tipo"] == "B"
        assert acred.datos_especificos["incluye_remolque"] is False

    def test_curso_interno_pc(self):
        """Curso interno con categoria FORMACION_INTERNA, sin número."""
        acred = AcreditacionCreate(
            tipo_id=uuid4(),
            categoria=CategoriaAcreditacion.FORMACION_INTERNA,
            fecha_obtencion=date(2024, 3, 10),
        )
        assert acred.categoria == CategoriaAcreditacion.FORMACION_INTERNA
        assert acred.numero is None
        assert acred.entidad_emisora is None

    def test_falta_tipo_id_obligatorio(self):
        with pytest.raises(ValidationError) as exc:
            AcreditacionCreate(
                categoria=CategoriaAcreditacion.LICENCIA_OFICIAL,
                fecha_obtencion=date(2020, 6, 15),
            )
        assert any(e["loc"] == ("tipo_id",) for e in exc.value.errors())

    def test_falta_categoria_obligatorio(self):
        with pytest.raises(ValidationError) as exc:
            AcreditacionCreate(
                tipo_id=uuid4(),
                fecha_obtencion=date(2020, 6, 15),
            )
        assert any(e["loc"] == ("categoria",) for e in exc.value.errors())

    def test_categoria_invalida(self):
        with pytest.raises(ValidationError):
            AcreditacionCreate(
                tipo_id=uuid4(),
                categoria="categoria_inexistente",
                fecha_obtencion=date(2020, 6, 15),
            )

    def test_numero_demasiado_largo(self):
        with pytest.raises(ValidationError):
            AcreditacionCreate(
                tipo_id=uuid4(),
                categoria=CategoriaAcreditacion.LICENCIA_OFICIAL,
                fecha_obtencion=date(2020, 6, 15),
                numero="X" * 101,
            )


class TestAcreditacionUpdate:
    """PATCH `/acreditaciones/{id}` — todos los campos opcionales."""

    def test_update_solo_fecha_caducidad(self):
        update = AcreditacionUpdate(fecha_caducidad=date(2035, 1, 1))
        assert update.fecha_caducidad == date(2035, 1, 1)
        assert update.tipo_id is None
        assert update.categoria is None

    def test_update_categoria_reclasificacion(self):
        """Reclasificar una acreditación de OTRO a LICENCIA_OFICIAL."""
        update = AcreditacionUpdate(categoria=CategoriaAcreditacion.LICENCIA_OFICIAL)
        assert update.categoria == CategoriaAcreditacion.LICENCIA_OFICIAL


class TestAcreditacionResponse:
    """Respuesta GET con tipo expandido."""

    def test_response_con_tipo_expandido(self):
        tipo = TipoAcreditacionResponse(
            id=uuid4(),
            codigo="CARNET_CONDUCIR",
            nombre="Carnet de conducir",
            categoria=CategoriaAcreditacion.LICENCIA_OFICIAL,
            activo=True,
        )
        response = AcreditacionResponse(
            id=uuid4(),
            voluntario_id=uuid4(),
            tipo_id=tipo.id,
            categoria=CategoriaAcreditacion.LICENCIA_OFICIAL,
            fecha_obtencion=date(2020, 6, 15),
            tipo=tipo,
        )
        assert response.tipo.codigo == "CARNET_CONDUCIR"
        assert response.tipo.activo is True


class TestTipoAcreditacionResponse:
    """Catálogo (solo lectura)."""

    def test_tipo_con_campos_schema(self):
        tipo = TipoAcreditacionResponse(
            id=uuid4(),
            codigo="ADR_MERCANCIAS_PELIGROSAS",
            nombre="ADR Mercancías Peligrosas",
            categoria=CategoriaAcreditacion.LICENCIA_OFICIAL,
            campos_schema={"clases": ["I", "II", "III"]},
            activo=True,
        )
        assert tipo.campos_schema == {"clases": ["I", "II", "III"]}

    def test_tipo_otro_sin_campos_schema(self):
        tipo = TipoAcreditacionResponse(
            id=uuid4(),
            codigo="OTRO",
            nombre="Otra acreditación",
            categoria=CategoriaAcreditacion.OTRO,
            activo=True,
        )
        assert tipo.campos_schema is None
