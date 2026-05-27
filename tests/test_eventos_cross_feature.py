"""Tests cross-feature del audit log de voluntarios (EN-02-04 / US-02-06).

Verifican que cada acción de los services existentes (voluntarios,
servicios, fichajes, inventario) genera la fila correspondiente en
``voluntario_eventos`` con el ``actor_keycloak_id`` propagado.

No mockean las capas: ejercitan los services reales contra Postgres
real y leen ``voluntario_eventos`` con el repository del audit log
para asertar tipos y payloads.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from app.models.asignacion_material import TipoAsignacion
from app.models.servicio import EstadoServicio
from app.models.voluntario_evento import TipoEventoVoluntario, VoluntarioEvento
from app.repositories import voluntario_evento as eventos_repo
from app.schemas.voluntario import VoluntarioCreate
from app.services import fichajes as fichajes_service
from app.services import inventario as inventario_service
from app.services import servicios as servicios_service
from app.services import voluntarios as voluntarios_service


@pytest.fixture
def yo(make_voluntario):
    return make_voluntario(keycloak_id="kc-yo")


def _eventos_por_tipo(
    db_session, voluntario_id, tipo: TipoEventoVoluntario
) -> list[VoluntarioEvento]:
    stmt = select(VoluntarioEvento).where(
        VoluntarioEvento.voluntario_id == voluntario_id,
        VoluntarioEvento.tipo_evento == tipo,
    )
    return list(db_session.exec(stmt).all())


class TestVoluntariosService:
    def test_crear_genera_evento_alta(self, db_session):
        data = VoluntarioCreate(
            nombre="Carla Ruiz",
            telefono="+34644444444",
            municipio="Zuera",
            fecha_nacimiento=datetime(1995, 4, 1).date(),
            dni="44444444D",
        )
        voluntario = voluntarios_service.crear(
            db_session,
            data=data,
            keycloak_id="kc-carla",
            actor_keycloak_id="kc-admin",
        )

        eventos = _eventos_por_tipo(
            db_session, voluntario.id, TipoEventoVoluntario.ALTA
        )
        assert len(eventos) == 1
        assert eventos[0].actor_keycloak_id == "kc-admin"
        assert eventos[0].payload["nombre"] == "Carla Ruiz"
        assert eventos[0].payload["keycloak_id"] == "kc-carla"

    def test_dar_baja_genera_evento_baja(self, db_session, yo):
        voluntarios_service.dar_baja(
            db_session, yo.id, actor_keycloak_id="kc-admin"
        )
        eventos = _eventos_por_tipo(
            db_session, yo.id, TipoEventoVoluntario.BAJA
        )
        assert len(eventos) == 1
        assert eventos[0].actor_keycloak_id == "kc-admin"

    def test_anonimizar_genera_evento_sin_pii(self, db_session, yo):
        voluntarios_service.anonimizar(
            db_session, yo.id, actor_keycloak_id="kc-coordinador"
        )
        eventos = _eventos_por_tipo(
            db_session, yo.id, TipoEventoVoluntario.ANONIMIZACION
        )
        assert len(eventos) == 1
        # El payload contiene el placeholder pero NO datos personales.
        assert "Voluntario anonimizado" in eventos[0].payload["placeholder"]
        assert "nombre" not in eventos[0].payload
        assert "dni" not in eventos[0].payload


class TestServiciosService:
    def test_apuntarse_propio_genera_evento_inscripcion_via_self_service(
        self, db_session, yo, make_servicio
    ):
        servicio = make_servicio(estado=EstadoServicio.PUBLICADO)

        servicios_service.apuntarse_propio(
            db_session,
            servicio_id=servicio.id,
            voluntario_id=yo.id,
            actor_keycloak_id="kc-yo",
        )

        eventos = _eventos_por_tipo(
            db_session, yo.id, TipoEventoVoluntario.INSCRIPCION_SERVICIO
        )
        assert len(eventos) == 1
        assert eventos[0].payload["via"] == "self_service"
        assert eventos[0].payload["servicio_id"] == str(servicio.id)
        assert eventos[0].actor_keycloak_id == "kc-yo"

    def test_desapuntarse_propio_genera_evento_baja_inscripcion(
        self, db_session, yo, make_servicio
    ):
        servicio = make_servicio(estado=EstadoServicio.PUBLICADO)
        servicios_service.apuntarse_propio(
            db_session,
            servicio_id=servicio.id,
            voluntario_id=yo.id,
            actor_keycloak_id="kc-yo",
        )
        servicios_service.desapuntarse_propio(
            db_session,
            servicio_id=servicio.id,
            voluntario_id=yo.id,
            actor_keycloak_id="kc-yo",
        )

        eventos = _eventos_por_tipo(
            db_session, yo.id, TipoEventoVoluntario.BAJA_INSCRIPCION
        )
        assert len(eventos) == 1
        assert eventos[0].payload["servicio_id"] == str(servicio.id)

    def test_convocar_genera_un_evento_por_voluntario_via_convocatoria(
        self, db_session, yo, make_voluntario, make_servicio
    ):
        otro = make_voluntario(
            keycloak_id="kc-otro", dni="77777777Y", nombre="Otro"
        )
        servicio = make_servicio(estado=EstadoServicio.PUBLICADO)

        servicios_service.convocar(
            db_session,
            servicio.id,
            voluntario_ids=[yo.id, otro.id],
            actor_keycloak_id="kc-mando",
        )

        for voluntario_id in (yo.id, otro.id):
            eventos = _eventos_por_tipo(
                db_session, voluntario_id, TipoEventoVoluntario.INSCRIPCION_SERVICIO
            )
            assert len(eventos) == 1
            assert eventos[0].payload["via"] == "convocatoria"
            assert eventos[0].actor_keycloak_id == "kc-mando"


class TestFichajesService:
    def test_fichar_entrada_y_salida_genera_dos_eventos(
        self, db_session, yo, make_servicio
    ):
        servicio = make_servicio(estado=EstadoServicio.PUBLICADO)
        servicios_service.apuntarse_propio(
            db_session,
            servicio_id=servicio.id,
            voluntario_id=yo.id,
            actor_keycloak_id="kc-yo",
        )
        # Convocar lo deja en ACTIVO sin moverlo si ya está PUBLICADO.
        servicios_service.convocar(
            db_session,
            servicio.id,
            voluntario_ids=[yo.id],
            actor_keycloak_id="kc-mando",
        )

        fichajes_service.fichar_entrada(
            db_session,
            servicio_id=servicio.id,
            voluntario_id=yo.id,
            actor_keycloak_id="kc-yo",
        )
        fichajes_service.fichar_salida(
            db_session,
            servicio_id=servicio.id,
            voluntario_id=yo.id,
            actor_keycloak_id="kc-yo",
        )

        entradas = _eventos_por_tipo(
            db_session, yo.id, TipoEventoVoluntario.FICHAJE_ENTRADA
        )
        salidas = _eventos_por_tipo(
            db_session, yo.id, TipoEventoVoluntario.FICHAJE_SALIDA
        )
        assert len(entradas) == 1
        assert len(salidas) == 1
        assert entradas[0].payload["servicio_id"] == str(servicio.id)
        assert salidas[0].payload["automatico"] is False
        assert salidas[0].actor_keycloak_id == "kc-yo"

    def test_cerrar_servicio_genera_fichaje_salida_automatica(
        self, db_session, yo, make_servicio
    ):
        servicio = make_servicio(estado=EstadoServicio.PUBLICADO)
        servicios_service.apuntarse_propio(
            db_session,
            servicio_id=servicio.id,
            voluntario_id=yo.id,
            actor_keycloak_id="kc-yo",
        )
        servicios_service.convocar(
            db_session,
            servicio.id,
            voluntario_ids=[yo.id],
            actor_keycloak_id="kc-mando",
        )
        fichajes_service.fichar_entrada(
            db_session,
            servicio_id=servicio.id,
            voluntario_id=yo.id,
            actor_keycloak_id="kc-yo",
        )

        # El mando cierra el servicio sin que el voluntario ficheo salida.
        servicios_service.cerrar(
            db_session,
            servicio.id,
            actor_keycloak_id="kc-mando",
            fecha_cierre=datetime.now() + timedelta(hours=3),
        )

        salidas = _eventos_por_tipo(
            db_session, yo.id, TipoEventoVoluntario.FICHAJE_SALIDA
        )
        assert len(salidas) == 1
        # La salida automática debe llevar `automatico=True` y el actor
        # del cierre (el mando), no del voluntario.
        assert salidas[0].payload["automatico"] is True
        assert salidas[0].actor_keycloak_id == "kc-mando"


class TestInventarioService:
    def test_asignar_y_devolver_material_genera_eventos_simetricos(
        self, db_session, yo, make_material
    ):
        from app.models.material import TipoMaterial

        casco = make_material(tipo=TipoMaterial.PERSONAL, cantidad=2)

        inventario_service.asignar_material_a_voluntario(
            db_session,
            material_id=casco.id,
            voluntario_id=yo.id,
            tipo=TipoAsignacion.PERSONAL,
            cantidad=1,
            actor_keycloak_id="kc-jefe",
        )

        asignaciones_eventos = _eventos_por_tipo(
            db_session, yo.id, TipoEventoVoluntario.ASIGNACION_MATERIAL
        )
        assert len(asignaciones_eventos) == 1
        assert asignaciones_eventos[0].payload["material_id"] == str(casco.id)
        assert asignaciones_eventos[0].payload["tipo_asignacion"] == "personal"
        assert asignaciones_eventos[0].actor_keycloak_id == "kc-jefe"

        inventario_service.devolver_material(
            db_session,
            material_id=casco.id,
            voluntario_id=yo.id,
            observaciones="OK",
            actor_keycloak_id="kc-jefe",
        )

        devoluciones_eventos = _eventos_por_tipo(
            db_session, yo.id, TipoEventoVoluntario.DEVOLUCION_MATERIAL
        )
        assert len(devoluciones_eventos) == 1
        assert devoluciones_eventos[0].payload["material_id"] == str(casco.id)
        assert devoluciones_eventos[0].payload["observaciones"] == "OK"


class TestHistorialAgregado:
    def test_historial_acumula_acciones_de_distintos_modulos(
        self,
        db_session,
        yo,
        make_voluntario,  # noqa: ARG002
        make_servicio,
        make_material,
    ):
        from app.models.material import TipoMaterial

        # Acción 1: asignar rol.
        from app.models.rol import Rol

        rol_voluntario = db_session.exec(
            select(Rol).where(Rol.nombre == "voluntario")
        ).first()
        voluntarios_service.asignar_rol(
            db_session,
            voluntario_id=yo.id,
            rol_id=rol_voluntario.id,
            actor_keycloak_id="kc-admin",
        )

        # Acción 2: inscripción + fichaje + cierre.
        servicio = make_servicio(estado=EstadoServicio.PUBLICADO)
        servicios_service.apuntarse_propio(
            db_session,
            servicio_id=servicio.id,
            voluntario_id=yo.id,
            actor_keycloak_id="kc-yo",
        )

        # Acción 3: asignación material.
        material = make_material(tipo=TipoMaterial.PERSONAL, cantidad=5)
        inventario_service.asignar_material_a_voluntario(
            db_session,
            material_id=material.id,
            voluntario_id=yo.id,
            tipo=TipoAsignacion.PERSONAL,
            cantidad=1,
            actor_keycloak_id="kc-jefe",
        )

        # El historial paginado debe traer las 3 acciones, más recientes
        # primero, sin necesidad de filtros.
        items, total = eventos_repo.list_by_voluntario(
            db_session, voluntario_id=yo.id, limit=50
        )
        tipos_observados = [e.tipo_evento for e in items]
        assert total == 3
        # Comprobamos el conjunto (no el orden exacto inter-segundos) para
        # robustez frente a colisiones de timestamp.
        assert set(tipos_observados) == {
            TipoEventoVoluntario.CAMBIO_ROL_ASIGNADO,
            TipoEventoVoluntario.INSCRIPCION_SERVICIO,
            TipoEventoVoluntario.ASIGNACION_MATERIAL,
        }
