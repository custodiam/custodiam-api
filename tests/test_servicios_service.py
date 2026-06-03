"""Tests del Service de servicios (EN-03-02 + EN-03-03 + EN-03-04).

Cubren la máquina de estados, las excepciones de dominio y la lógica de
inscripciones self-service. La capa HTTP se verifica en
`test_servicios_router.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.models.inscripcion_servicio import TipoInscripcion
from app.models.servicio import EstadoServicio, TipoServicio
from app.schemas.servicio import ServicioCreate, ServicioUpdate
from app.services import servicios as service

# ---------------------------------------------------------------------------
# Crear
# ---------------------------------------------------------------------------


class TestCrear:
    def _payload(self, **overrides):
        base = dict(
            titulo="Servicio prueba",
            tipo=TipoServicio.PREVENTIVO,
            fecha_inicio=datetime(2026, 7, 1, 9, 0),
            fecha_fin=datetime(2026, 7, 1, 14, 0),
            ubicacion="Zaragoza",
        )
        base.update(overrides)
        return ServicioCreate(**base)

    def test_crear_preventivo_arranca_en_borrador(self, db_session):
        s = service.crear(db_session, data=self._payload())
        assert s.estado == EstadoServicio.BORRADOR
        assert s.tipo == TipoServicio.PREVENTIVO

    def test_crear_formacion_arranca_en_borrador(self, db_session):
        s = service.crear(
            db_session, data=self._payload(tipo=TipoServicio.FORMACION)
        )
        assert s.estado == EstadoServicio.BORRADOR

    def test_crear_emergencia_arranca_en_activo(self, db_session):
        s = service.crear(
            db_session, data=self._payload(tipo=TipoServicio.EMERGENCIA)
        )
        assert s.estado == EstadoServicio.ACTIVO

    def test_crear_propaga_keycloak_id(self, db_session):
        s = service.crear(
            db_session,
            data=self._payload(),
            creado_por_keycloak_id="kc-jefe-1",
        )
        assert s.creado_por_keycloak_id == "kc-jefe-1"


# ---------------------------------------------------------------------------
# Actualizar
# ---------------------------------------------------------------------------


class TestActualizar:
    def test_actualizar_aplica_campos(self, db_session, servicio_borrador):
        s = service.actualizar(
            db_session,
            servicio_borrador.id,
            ServicioUpdate(ubicacion="Huesca"),
        )
        assert s.ubicacion == "Huesca"

    def test_actualizar_inexistente_lanza_404(self, db_session):
        with pytest.raises(service.ServicioNoEncontrado):
            service.actualizar(
                db_session, uuid.uuid4(), ServicioUpdate(ubicacion="x")
            )


# ---------------------------------------------------------------------------
# Eliminar (borrado físico — corrección de errores de creación)
# ---------------------------------------------------------------------------


class TestEliminar:
    """Decisión del PO: el borrado SIEMPRE procede y arrastra en cascada
    inscripciones, fichajes y asignaciones de inventario del servicio."""

    def test_eliminar_servicio_vacio_borra(self, db_session, servicio_borrador):
        from app.repositories import servicios as repo

        service.eliminar(db_session, servicio_borrador.id)
        assert repo.get(db_session, servicio_borrador.id) is None

    def test_eliminar_inexistente_lanza_404(self, db_session):
        with pytest.raises(service.ServicioNoEncontrado):
            service.eliminar(db_session, uuid.uuid4())

    def test_eliminar_con_inscripcion_borra_igualmente(
        self, db_session, servicio_borrador, voluntario
    ):
        from app.repositories import servicios as repo

        repo.upsert_inscripcion(
            db_session,
            servicio_id=servicio_borrador.id,
            voluntario_id=voluntario.id,
            tipo=TipoInscripcion.INSCRITO,
            fecha=datetime(2026, 7, 1, 9, 0),
        )
        service.eliminar(db_session, servicio_borrador.id)
        # El servicio y su inscripción desaparecen.
        assert repo.get(db_session, servicio_borrador.id) is None
        assert repo.count_inscripciones(db_session, servicio_borrador.id) == 0

    def test_eliminar_con_material_asignado_borra_igualmente(
        self, db_session, servicio_borrador, make_material
    ):
        from app.models.material import TipoMaterial
        from app.repositories import servicios as repo
        from app.services import inventario as inv_service

        m = make_material(tipo=TipoMaterial.SERVICIO, cantidad=5)
        inv_service.asignar_material_a_servicio(
            db_session,
            material_id=m.id,
            servicio_id=servicio_borrador.id,
            cantidad=1,
        )
        service.eliminar(db_session, servicio_borrador.id)
        assert repo.get(db_session, servicio_borrador.id) is None
        assert (
            inv_service.contar_asignaciones_de_servicio(
                db_session, servicio_borrador.id
            )
            == 0
        )

    def test_eliminar_arrastra_vehiculo_inscripcion_y_fichaje(
        self, db_session, make_servicio, make_vehiculo, voluntario
    ):
        """Borrado en cascada completo: un servicio con un vehículo asignado,
        una inscripción y un fichaje se borra y no deja filas hijas."""

        from app.models.servicio import EstadoServicio
        from app.repositories import fichajes as fichajes_repo
        from app.repositories import servicios as repo
        from app.services import inventario as inv_service

        # Servicio activo (admite fichaje y asignación de vehículo).
        servicio = make_servicio(estado=EstadoServicio.ACTIVO)

        # Una inscripción del voluntario.
        repo.upsert_inscripcion(
            db_session,
            servicio_id=servicio.id,
            voluntario_id=voluntario.id,
            tipo=TipoInscripcion.INSCRITO,
            fecha=datetime(2026, 7, 1, 9, 0),
        )

        # Un vehículo asignado al servicio.
        vehiculo = make_vehiculo()
        inv_service.asignar_vehiculo_a_servicio(
            db_session,
            vehiculo_id=vehiculo.id,
            servicio_id=servicio.id,
        )

        # Un fichaje del voluntario en el servicio.
        fichajes_repo.create(
            db_session,
            data=dict(
                servicio_id=servicio.id,
                voluntario_id=voluntario.id,
                hora_entrada=datetime(2026, 7, 1, 9, 0),
                hora_salida=None,
                automatico=False,
            ),
        )

        service.eliminar(db_session, servicio.id)

        # No queda el servicio ni ninguna fila hija.
        assert repo.get(db_session, servicio.id) is None
        assert repo.count_inscripciones(db_session, servicio.id) == 0
        assert (
            inv_service.contar_asignaciones_de_servicio(db_session, servicio.id)
            == 0
        )
        assert fichajes_repo.list_por_servicio(db_session, servicio.id) == []
        # El vehículo se libera a OPERATIVO (no se borra).
        from app.models.material import EstadoInventario

        vehiculo_tras = inv_service.obtener_vehiculo(db_session, vehiculo.id)
        assert vehiculo_tras.estado == EstadoInventario.OPERATIVO


# ---------------------------------------------------------------------------
# Máquina de estados (EN-03-03)
# ---------------------------------------------------------------------------


class TestPublicar:
    def test_publicar_borrador(self, db_session, servicio_borrador):
        s = service.publicar(db_session, servicio_borrador.id)
        assert s.estado == EstadoServicio.PUBLICADO

    def test_publicar_ya_publicado_falla(self, db_session, servicio_publicado):
        with pytest.raises(service.TransicionEstadoInvalida) as exc:
            service.publicar(db_session, servicio_publicado.id)
        assert exc.value.actual == EstadoServicio.PUBLICADO
        assert exc.value.solicitado == EstadoServicio.PUBLICADO

    def test_publicar_servicio_activo_falla(self, db_session, servicio_activo):
        with pytest.raises(service.TransicionEstadoInvalida):
            service.publicar(db_session, servicio_activo.id)

    def test_publicar_inexistente_lanza_404(self, db_session):
        with pytest.raises(service.ServicioNoEncontrado):
            service.publicar(db_session, uuid.uuid4())


class TestConvocar:
    """Convocar SOLO notifica y activa: no crea inscripciones (decisión PO).

    El contador de inscritos no se infla por la convocatoria; solo refleja
    a quien se inscribe por su cuenta. Estos tests verifican la transición
    de estado y que el servicio no gana inscripciones al convocar.
    """

    def test_convocar_desde_publicado_pasa_a_activo(
        self, db_session, servicio_publicado, voluntario
    ):
        s = service.convocar(
            db_session,
            servicio_publicado.id,
            voluntario_ids=[voluntario.id],
        )
        assert s.estado == EstadoServicio.ACTIVO
        # No se crea ninguna inscripción al convocar.
        assert service.obtener(db_session, servicio_publicado.id).inscritos_count == 0

    def test_convocar_emergencia_desde_borrador_pasa_a_activo(
        self, db_session, make_servicio, voluntario
    ):
        emergencia = make_servicio(tipo=TipoServicio.EMERGENCIA)
        # Forzamos estado BORRADOR (la factoría lo deja por defecto en BORRADOR
        # también para EMERGENCIA en este test específico).
        s = service.convocar(
            db_session, emergencia.id, voluntario_ids=[voluntario.id]
        )
        assert s.estado == EstadoServicio.ACTIVO

    def test_convocar_preventivo_desde_borrador_falla(
        self, db_session, servicio_borrador, voluntario
    ):
        with pytest.raises(service.TransicionEstadoInvalida):
            service.convocar(
                db_session,
                servicio_borrador.id,
                voluntario_ids=[voluntario.id],
            )

    def test_convocar_sin_lista_activa_el_servicio(
        self, db_session, servicio_publicado, make_voluntario
    ):
        make_voluntario(nombre="Ana")
        make_voluntario(nombre="Bea")
        # Un voluntario en baja no debe entrar en el universo de notificados.
        from app.models.voluntario import EstadoVoluntario

        make_voluntario(nombre="Carlos baja", estado=EstadoVoluntario.BAJA)
        s = service.convocar(
            db_session, servicio_publicado.id, voluntario_ids=None
        )
        # Activa el servicio sin crear inscripciones para nadie.
        assert s.estado == EstadoServicio.ACTIVO
        assert service.obtener(db_session, servicio_publicado.id).inscritos_count == 0

    def test_convocar_no_toca_la_inscripcion_existente(
        self, db_session, servicio_publicado, voluntario
    ):
        # Si el voluntario ya se inscribió por su cuenta, convocar no la
        # promociona a CONVOCADO ni crea otra: solo activa el servicio.
        service.apuntarse_propio(
            db_session,
            servicio_id=servicio_publicado.id,
            voluntario_id=voluntario.id,
        )
        service.convocar(
            db_session,
            servicio_publicado.id,
            voluntario_ids=[voluntario.id],
        )
        from app.repositories import servicios as repo

        inscripcion = repo.get_inscripcion(
            db_session,
            servicio_id=servicio_publicado.id,
            voluntario_id=voluntario.id,
        )
        assert inscripcion is not None
        assert inscripcion.tipo == TipoInscripcion.INSCRITO
        assert service.obtener(db_session, servicio_publicado.id).inscritos_count == 1

    def test_convocar_cerrado_falla(self, db_session, make_servicio, voluntario):
        cerrado = make_servicio(estado=EstadoServicio.CERRADO)
        with pytest.raises(service.TransicionEstadoInvalida):
            service.convocar(
                db_session, cerrado.id, voluntario_ids=[voluntario.id]
            )


class TestInscritosCountTrasOperaciones:
    """`inscritos_count` refleja el total real de inscritos self-service.

    Convocar no inscribe a nadie (decisión PO), así que no toca el contador;
    solo lo mueven `apuntarse_propio` y `desapuntarse_propio`.
    """

    def test_convocar_no_incrementa_inscritos_count(
        self, db_session, servicio_publicado, make_voluntario
    ):
        v1 = make_voluntario(nombre="Ana")
        v2 = make_voluntario(nombre="Bea")
        service.convocar(
            db_session,
            servicio_publicado.id,
            voluntario_ids=[v1.id, v2.id],
        )
        s = service.obtener(db_session, servicio_publicado.id)
        assert s.inscritos_count == 0

    def test_apuntarse_incrementa_inscritos_count(
        self, db_session, servicio_publicado, voluntario
    ):
        antes = service.obtener(db_session, servicio_publicado.id)
        assert antes.inscritos_count == 0
        service.apuntarse_propio(
            db_session,
            servicio_id=servicio_publicado.id,
            voluntario_id=voluntario.id,
        )
        despues = service.obtener(db_session, servicio_publicado.id)
        assert despues.inscritos_count == 1

    def test_desapuntarse_decrementa_inscritos_count(
        self, db_session, servicio_publicado, voluntario
    ):
        service.apuntarse_propio(
            db_session,
            servicio_id=servicio_publicado.id,
            voluntario_id=voluntario.id,
        )
        service.desapuntarse_propio(
            db_session,
            servicio_id=servicio_publicado.id,
            voluntario_id=voluntario.id,
        )
        s = service.obtener(db_session, servicio_publicado.id)
        assert s.inscritos_count == 0


class TestCerrar:
    def test_cerrar_servicio_activo(self, db_session, servicio_activo):
        s = service.cerrar(
            db_session,
            servicio_activo.id,
            observaciones="OK sin incidencias",
        )
        assert s.estado == EstadoServicio.CERRADO
        assert s.observaciones_cierre == "OK sin incidencias"
        assert s.fecha_cierre is not None

    def test_cerrar_borrador_falla(self, db_session, servicio_borrador):
        with pytest.raises(service.TransicionEstadoInvalida):
            service.cerrar(db_session, servicio_borrador.id)

    def test_cerrar_publicado_falla(self, db_session, servicio_publicado):
        with pytest.raises(service.TransicionEstadoInvalida):
            service.cerrar(db_session, servicio_publicado.id)

    def test_cerrar_ya_cerrado_falla(self, db_session, make_servicio):
        cerrado = make_servicio(estado=EstadoServicio.CERRADO)
        with pytest.raises(service.TransicionEstadoInvalida):
            service.cerrar(db_session, cerrado.id)


# ---------------------------------------------------------------------------
# Self-service inscripciones (EN-03-04 / CU-04)
# ---------------------------------------------------------------------------


class TestApuntarsePropio:
    def test_apuntarse_a_publicado(
        self, db_session, servicio_publicado, voluntario
    ):
        inscripcion = service.apuntarse_propio(
            db_session,
            servicio_id=servicio_publicado.id,
            voluntario_id=voluntario.id,
        )
        assert inscripcion.tipo == TipoInscripcion.INSCRITO

    def test_apuntarse_a_activo_funciona(
        self, db_session, servicio_activo, voluntario
    ):
        # Un voluntario aún puede sumarse a una emergencia en curso.
        inscripcion = service.apuntarse_propio(
            db_session,
            servicio_id=servicio_activo.id,
            voluntario_id=voluntario.id,
        )
        assert inscripcion.tipo == TipoInscripcion.INSCRITO

    def test_apuntarse_a_borrador_falla(
        self, db_session, servicio_borrador, voluntario
    ):
        with pytest.raises(service.InscripcionNoPermitidaEnEsteEstado):
            service.apuntarse_propio(
                db_session,
                servicio_id=servicio_borrador.id,
                voluntario_id=voluntario.id,
            )

    def test_apuntarse_a_cerrado_falla(
        self, db_session, make_servicio, voluntario
    ):
        cerrado = make_servicio(estado=EstadoServicio.CERRADO)
        with pytest.raises(service.InscripcionNoPermitidaEnEsteEstado):
            service.apuntarse_propio(
                db_session,
                servicio_id=cerrado.id,
                voluntario_id=voluntario.id,
            )

    def test_apuntarse_dos_veces_falla(
        self, db_session, servicio_publicado, voluntario
    ):
        service.apuntarse_propio(
            db_session,
            servicio_id=servicio_publicado.id,
            voluntario_id=voluntario.id,
        )
        with pytest.raises(service.YaInscrito):
            service.apuntarse_propio(
                db_session,
                servicio_id=servicio_publicado.id,
                voluntario_id=voluntario.id,
            )

    def test_apuntarse_a_servicio_inexistente_lanza_404(
        self, db_session, voluntario
    ):
        with pytest.raises(service.ServicioNoEncontrado):
            service.apuntarse_propio(
                db_session,
                servicio_id=uuid.uuid4(),
                voluntario_id=voluntario.id,
            )


class TestDesapuntarsePropio:
    def test_desapuntarse_borra_la_fila(
        self, db_session, servicio_publicado, voluntario
    ):
        service.apuntarse_propio(
            db_session,
            servicio_id=servicio_publicado.id,
            voluntario_id=voluntario.id,
        )
        service.desapuntarse_propio(
            db_session,
            servicio_id=servicio_publicado.id,
            voluntario_id=voluntario.id,
        )
        # Tras la baja, no quedan inscripciones de ese voluntario.
        from app.repositories import servicios as repo

        assert (
            repo.get_inscripcion(
                db_session,
                servicio_id=servicio_publicado.id,
                voluntario_id=voluntario.id,
            )
            is None
        )

    def test_desapuntarse_sin_inscripcion_lanza_404(
        self, db_session, servicio_publicado, voluntario
    ):
        with pytest.raises(service.NoInscrito):
            service.desapuntarse_propio(
                db_session,
                servicio_id=servicio_publicado.id,
                voluntario_id=voluntario.id,
            )

    def test_desapuntarse_convocatoria_funciona(
        self, db_session, servicio_publicado, voluntario
    ):
        # Decisión del PO: un voluntario CONVOCADO también puede darse de
        # baja por su cuenta (es libre de no acudir aunque lo convoquen).
        from app.repositories import servicios as repo

        repo.upsert_inscripcion(
            db_session,
            servicio_id=servicio_publicado.id,
            voluntario_id=voluntario.id,
            tipo=TipoInscripcion.CONVOCADO,
            fecha=datetime(2026, 7, 1, 9, 0),
        )
        service.desapuntarse_propio(
            db_session,
            servicio_id=servicio_publicado.id,
            voluntario_id=voluntario.id,
        )
        assert (
            repo.get_inscripcion(
                db_session,
                servicio_id=servicio_publicado.id,
                voluntario_id=voluntario.id,
            )
            is None
        )


# ---------------------------------------------------------------------------
# Lecturas auxiliares
# ---------------------------------------------------------------------------


class TestObtenerYListar:
    def test_obtener_existente(self, db_session, servicio_borrador):
        s = service.obtener(db_session, servicio_borrador.id)
        assert s.id == servicio_borrador.id

    def test_obtener_inexistente_lanza_404(self, db_session):
        with pytest.raises(service.ServicioNoEncontrado):
            service.obtener(db_session, uuid.uuid4())

    def test_listar_devuelve_items_y_total(self, db_session, make_servicio):
        make_servicio(titulo="Uno")
        make_servicio(titulo="Dos")
        items, total = service.listar(db_session)
        assert total == 2
        assert len(items) == 2

    def test_listar_voluntarios_404_si_no_existe_servicio(self, db_session):
        with pytest.raises(service.ServicioNoEncontrado):
            service.listar_voluntarios(db_session, uuid.uuid4())

    def test_listar_voluntarios_devuelve_pares(
        self, db_session, servicio_publicado, voluntario
    ):
        service.apuntarse_propio(
            db_session,
            servicio_id=servicio_publicado.id,
            voluntario_id=voluntario.id,
        )
        pares = service.listar_voluntarios(db_session, servicio_publicado.id)
        assert len(pares) == 1
        v, i = pares[0]
        assert v.id == voluntario.id
        assert i.tipo == TipoInscripcion.INSCRITO
