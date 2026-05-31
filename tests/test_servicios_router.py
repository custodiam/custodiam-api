"""Tests E2E del router de servicios (EN-03-02 / EN-03-03 / EN-03-04).

Verifican los códigos HTTP, la forma del payload y la matriz RBAC
declarativa. La lógica de negocio en profundidad se cubre en
`test_servicios_service.py` y las queries en
`test_servicios_repository.py`.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.permissions import Permission
from app.models.servicio import EstadoServicio

BASE = "/api/v1/servicios"


# ---------------------------------------------------------------------------
# Anónimo: 401 en todos los endpoints
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", BASE),
        ("get", f"{BASE}/{uuid.uuid4()}"),
        ("post", BASE),
        ("patch", f"{BASE}/{uuid.uuid4()}"),
        ("post", f"{BASE}/{uuid.uuid4()}/publicar"),
        ("post", f"{BASE}/{uuid.uuid4()}/convocar"),
        ("post", f"{BASE}/{uuid.uuid4()}/cerrar"),
        ("post", f"{BASE}/{uuid.uuid4()}/inscribirse"),
        ("delete", f"{BASE}/{uuid.uuid4()}/inscribirse"),
        ("get", f"{BASE}/{uuid.uuid4()}/voluntarios"),
    ],
)
def test_endpoints_sin_token_devuelven_401(client, method, path):
    request = getattr(client, method)
    response = request(path) if method in {"get", "delete"} else request(path, json={})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /servicios y GET /servicios/{id}
# ---------------------------------------------------------------------------


class TestListarYObtener:
    def test_lista_vacia(self, authenticated_client):
        r = authenticated_client.get(BASE)
        assert r.status_code == 200
        assert r.json() == []
        assert r.headers["X-Total-Count"] == "0"

    def test_lista_con_servicios(self, authenticated_client, make_servicio):
        from datetime import datetime as _dt

        make_servicio(titulo="Romería", fecha_inicio=_dt(2026, 6, 1, 9, 0))
        make_servicio(titulo="Cabalgata", fecha_inicio=_dt(2026, 7, 1, 18, 0))
        r = authenticated_client.get(BASE)
        assert r.status_code == 200
        assert r.headers["X-Total-Count"] == "2"
        titulos = [s["titulo"] for s in r.json()]
        # Orden por fecha_inicio descendente.
        assert titulos == ["Cabalgata", "Romería"]

    def test_filtro_estado(self, authenticated_client, make_servicio):
        make_servicio(titulo="Activo 1", estado=EstadoServicio.ACTIVO)
        make_servicio(titulo="Borrador 1")
        r = authenticated_client.get(BASE, params={"estado": "activo"})
        assert r.status_code == 200
        assert {s["titulo"] for s in r.json()} == {"Activo 1"}

    def test_filtro_q_por_ubicacion(self, authenticated_client, make_servicio):
        make_servicio(titulo="A", ubicacion="Zuera")
        make_servicio(titulo="B", ubicacion="Huesca")
        r = authenticated_client.get(BASE, params={"q": "zuera"})
        assert r.status_code == 200
        assert {s["titulo"] for s in r.json()} == {"A"}

    def test_filtro_por_rango_de_fechas(self, authenticated_client, make_servicio):
        from datetime import datetime as _dt

        make_servicio(titulo="Mayo", fecha_inicio=_dt(2026, 5, 10, 9, 0))
        make_servicio(titulo="Junio", fecha_inicio=_dt(2026, 6, 15, 9, 0))
        make_servicio(titulo="Julio", fecha_inicio=_dt(2026, 7, 20, 9, 0))
        r = authenticated_client.get(
            BASE, params={"desde": "2026-06-01", "hasta": "2026-06-30"}
        )
        assert r.status_code == 200
        assert r.headers["X-Total-Count"] == "1"
        assert {s["titulo"] for s in r.json()} == {"Junio"}

    def test_filtro_hasta_incluye_servicios_del_ultimo_dia(
        self, authenticated_client, make_servicio
    ):
        # Un servicio a las 18:00 del día `hasta` debe entrar (rango
        # inclusivo del día completo, no recortado a las 00:00).
        from datetime import datetime as _dt

        make_servicio(titulo="Tarde", fecha_inicio=_dt(2026, 6, 30, 18, 0))
        r = authenticated_client.get(
            BASE, params={"desde": "2026-06-01", "hasta": "2026-06-30"}
        )
        assert r.status_code == 200
        assert {s["titulo"] for s in r.json()} == {"Tarde"}

    def test_filtro_desde_posterior_a_hasta_es_422(self, authenticated_client):
        r = authenticated_client.get(
            BASE, params={"desde": "2026-07-01", "hasta": "2026-06-01"}
        )
        assert r.status_code == 422

    def test_filtro_fecha_mal_formada_es_422(self, authenticated_client):
        r = authenticated_client.get(BASE, params={"desde": "no-es-fecha"})
        assert r.status_code == 422

    def test_obtener_existente(self, authenticated_client, servicio_borrador):
        r = authenticated_client.get(f"{BASE}/{servicio_borrador.id}")
        assert r.status_code == 200
        assert r.json()["id"] == str(servicio_borrador.id)

    def test_obtener_inexistente_es_404(self, authenticated_client):
        r = authenticated_client.get(f"{BASE}/{uuid.uuid4()}")
        assert r.status_code == 404

    def test_paginacion_limit_supera_200_es_422(self, authenticated_client):
        r = authenticated_client.get(BASE, params={"limit": 999})
        assert r.status_code == 422


class TestInscritosCountEnJson:
    """`inscritos_count` aparece en el JSON de lista y de detalle."""

    def _inscribir(self, db_session, servicio_id, voluntario_id):
        from datetime import datetime

        from app.models.inscripcion_servicio import (
            InscripcionServicio,
            TipoInscripcion,
        )

        db_session.add(
            InscripcionServicio(
                servicio_id=servicio_id,
                voluntario_id=voluntario_id,
                tipo=TipoInscripcion.INSCRITO,
                fecha=datetime(2026, 5, 27, 10, 0),
            )
        )
        db_session.commit()

    def test_lista_expone_inscritos_count_por_servicio(
        self, authenticated_client, make_servicio, make_voluntario, db_session
    ):
        from datetime import datetime as _dt

        # Servicio con 2 inscritos.
        s_dos = make_servicio(titulo="Con dos", fecha_inicio=_dt(2026, 7, 1, 9, 0))
        for _ in range(2):
            v = make_voluntario(nombre=f"V{uuid.uuid4().hex[:6]}")
            self._inscribir(db_session, s_dos.id, v.id)
        # Servicio sin inscritos.
        s_cero = make_servicio(titulo="Sin nadie", fecha_inicio=_dt(2026, 6, 1, 9, 0))
        # Servicio con 5 inscritos.
        s_cinco = make_servicio(titulo="Con cinco", fecha_inicio=_dt(2026, 8, 1, 9, 0))
        for _ in range(5):
            v = make_voluntario(nombre=f"V{uuid.uuid4().hex[:6]}")
            self._inscribir(db_session, s_cinco.id, v.id)

        r = authenticated_client.get(BASE)
        assert r.status_code == 200
        por_id = {s["id"]: s["inscritos_count"] for s in r.json()}
        assert por_id[str(s_dos.id)] == 2
        assert por_id[str(s_cero.id)] == 0
        assert por_id[str(s_cinco.id)] == 5

    def test_detalle_expone_inscritos_count(
        self, authenticated_client, servicio_publicado, make_voluntario, db_session
    ):
        for _ in range(3):
            v = make_voluntario(nombre=f"V{uuid.uuid4().hex[:6]}")
            self._inscribir(db_session, servicio_publicado.id, v.id)
        r = authenticated_client.get(f"{BASE}/{servicio_publicado.id}")
        assert r.status_code == 200
        assert r.json()["inscritos_count"] == 3

    def test_detalle_inscritos_count_tras_convocar(
        self, client_for_role, servicio_publicado, make_voluntario
    ):
        c = client_for_role(["jefe_equipo"])
        ids = [str(make_voluntario(nombre=f"V{i}").id) for i in range(5)]
        c.post(
            f"{BASE}/{servicio_publicado.id}/convocar",
            json={"voluntario_ids": ids},
        )
        r = c.get(f"{BASE}/{servicio_publicado.id}")
        assert r.status_code == 200
        assert r.json()["inscritos_count"] == 5


# ---------------------------------------------------------------------------
# POST /servicios
# ---------------------------------------------------------------------------


class TestCrear:
    def _payload(self, **overrides):
        base = dict(
            titulo="Servicio nuevo",
            tipo="preventivo",
            fecha_inicio="2026-08-01T09:00:00",
            fecha_fin="2026-08-01T14:00:00",
            ubicacion="Zaragoza",
        )
        base.update(overrides)
        return base

    def test_preventivo_como_jefe_equipo_devuelve_201(self, client_for_role):
        c = client_for_role(["jefe_equipo"])
        r = c.post(BASE, json=self._payload())
        assert r.status_code == 201
        body = r.json()
        assert body["estado"] == "borrador"

    def test_preventivo_como_secretario_funciona(self, client_for_role):
        c = client_for_role(["secretario"])
        r = c.post(BASE, json=self._payload())
        assert r.status_code == 201

    def test_emergencia_como_jefe_equipo_arranca_en_activo(
        self, client_for_role
    ):
        c = client_for_role(["jefe_equipo"])
        r = c.post(BASE, json=self._payload(tipo="emergencia"))
        assert r.status_code == 201
        assert r.json()["estado"] == "activo"

    def test_emergencia_como_secretario_es_403(self, client_for_role):
        # `secretario` no tiene `servicios.crear_emergencia`.
        c = client_for_role(["secretario"])
        r = c.post(BASE, json=self._payload(tipo="emergencia"))
        assert r.status_code == 403
        assert Permission.SERVICIOS_CREAR_EMERGENCIA.value in r.json()["detail"]

    def test_preventivo_como_voluntario_basico_es_403(
        self, authenticated_client
    ):
        r = authenticated_client.post(BASE, json=self._payload())
        assert r.status_code == 403

    def test_preventivo_como_tesorero_es_403(self, client_for_role):
        c = client_for_role(["tesorero"])
        r = c.post(BASE, json=self._payload())
        assert r.status_code == 403

    def test_alta_sin_campos_obligatorios_es_422(self, client_for_role):
        c = client_for_role(["jefe_equipo"])
        r = c.post(BASE, json={"titulo": "Solo titulo"})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /servicios/{id}
# ---------------------------------------------------------------------------


class TestActualizar:
    def test_patch_como_jefe_equipo(self, client_for_role, servicio_borrador):
        c = client_for_role(["jefe_equipo"])
        r = c.patch(
            f"{BASE}/{servicio_borrador.id}",
            json={"ubicacion": "Huesca"},
        )
        assert r.status_code == 200
        assert r.json()["ubicacion"] == "Huesca"

    def test_patch_inexistente_es_404(self, client_for_role):
        c = client_for_role(["jefe_equipo"])
        r = c.patch(f"{BASE}/{uuid.uuid4()}", json={"ubicacion": "x"})
        assert r.status_code == 404

    def test_patch_como_voluntario_es_403(
        self, authenticated_client, servicio_borrador
    ):
        r = authenticated_client.patch(
            f"{BASE}/{servicio_borrador.id}", json={"ubicacion": "x"}
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Transiciones de estado
# ---------------------------------------------------------------------------


class TestPublicar:
    def test_publicar_como_jefe_equipo(
        self, client_for_role, servicio_borrador
    ):
        c = client_for_role(["jefe_equipo"])
        r = c.post(f"{BASE}/{servicio_borrador.id}/publicar")
        assert r.status_code == 200
        assert r.json()["estado"] == "publicado"

    def test_publicar_servicio_activo_es_409(
        self, client_for_role, servicio_activo
    ):
        c = client_for_role(["jefe_equipo"])
        r = c.post(f"{BASE}/{servicio_activo.id}/publicar")
        assert r.status_code == 409
        assert "no permitida" in r.json()["detail"]

    def test_publicar_como_voluntario_es_403(
        self, authenticated_client, servicio_borrador
    ):
        r = authenticated_client.post(f"{BASE}/{servicio_borrador.id}/publicar")
        assert r.status_code == 403


class TestConvocar:
    def test_convocar_desde_publicado_pasa_a_activo(
        self, client_for_role, servicio_publicado, voluntario
    ):
        c = client_for_role(["jefe_equipo"])
        r = c.post(
            f"{BASE}/{servicio_publicado.id}/convocar",
            json={"voluntario_ids": [str(voluntario.id)]},
        )
        assert r.status_code == 200
        assert r.json()["estado"] == "activo"

    def test_convocar_sin_body_convoca_a_todos_los_activos(
        self, client_for_role, servicio_publicado, make_voluntario
    ):
        c = client_for_role(["jefe_equipo"])
        make_voluntario(nombre="Ana")
        make_voluntario(nombre="Bea")
        r = c.post(f"{BASE}/{servicio_publicado.id}/convocar")
        assert r.status_code == 200
        assert r.json()["estado"] == "activo"

    def test_convocar_preventivo_borrador_es_409(
        self, client_for_role, servicio_borrador, voluntario
    ):
        c = client_for_role(["jefe_equipo"])
        r = c.post(
            f"{BASE}/{servicio_borrador.id}/convocar",
            json={"voluntario_ids": [str(voluntario.id)]},
        )
        assert r.status_code == 409

    def test_convocar_como_secretario_es_403(
        self, client_for_role, servicio_publicado, voluntario
    ):
        # `secretario` no tiene `servicios.convocar`.
        c = client_for_role(["secretario"])
        r = c.post(
            f"{BASE}/{servicio_publicado.id}/convocar",
            json={"voluntario_ids": [str(voluntario.id)]},
        )
        assert r.status_code == 403


class TestCerrar:
    def test_cerrar_servicio_activo(
        self, client_for_role, servicio_activo
    ):
        c = client_for_role(["jefe_equipo"])
        r = c.post(
            f"{BASE}/{servicio_activo.id}/cerrar",
            json={"observaciones_cierre": "OK"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["estado"] == "cerrado"
        assert body["observaciones_cierre"] == "OK"

    def test_cerrar_borrador_es_409(
        self, client_for_role, servicio_borrador
    ):
        c = client_for_role(["jefe_equipo"])
        r = c.post(f"{BASE}/{servicio_borrador.id}/cerrar")
        assert r.status_code == 409


# ---------------------------------------------------------------------------
# Inscripciones (EN-03-04)
# ---------------------------------------------------------------------------


class TestInscribirse:
    def test_inscribirse_como_voluntario_publicado(
        self, authenticated_client, make_voluntario, servicio_publicado
    ):
        # El conftest define `test-user-id` como sub del JWT;
        # creamos un voluntario en BD que enlace ese sub.
        make_voluntario(keycloak_id="test-user-id")
        r = authenticated_client.post(
            f"{BASE}/{servicio_publicado.id}/inscribirse"
        )
        assert r.status_code == 201
        assert r.json()["id"] == str(servicio_publicado.id)

    def test_inscribirse_sin_voluntario_en_bd_es_404(
        self, authenticated_client, servicio_publicado
    ):
        # No creamos voluntario que enlace `test-user-id`.
        r = authenticated_client.post(
            f"{BASE}/{servicio_publicado.id}/inscribirse"
        )
        assert r.status_code == 404

    def test_inscribirse_dos_veces_es_409(
        self, authenticated_client, make_voluntario, servicio_publicado
    ):
        make_voluntario(keycloak_id="test-user-id")
        authenticated_client.post(f"{BASE}/{servicio_publicado.id}/inscribirse")
        r = authenticated_client.post(
            f"{BASE}/{servicio_publicado.id}/inscribirse"
        )
        assert r.status_code == 409

    def test_inscribirse_en_borrador_es_409(
        self, authenticated_client, make_voluntario, servicio_borrador
    ):
        make_voluntario(keycloak_id="test-user-id")
        r = authenticated_client.post(
            f"{BASE}/{servicio_borrador.id}/inscribirse"
        )
        assert r.status_code == 409

    def test_inscribirse_en_servicio_inexistente_es_404(
        self, authenticated_client, make_voluntario
    ):
        make_voluntario(keycloak_id="test-user-id")
        r = authenticated_client.post(f"{BASE}/{uuid.uuid4()}/inscribirse")
        assert r.status_code == 404


class TestDesapuntarse:
    def test_desapuntarse_borra_la_inscripcion(
        self, authenticated_client, make_voluntario, servicio_publicado
    ):
        make_voluntario(keycloak_id="test-user-id")
        authenticated_client.post(f"{BASE}/{servicio_publicado.id}/inscribirse")
        r = authenticated_client.delete(
            f"{BASE}/{servicio_publicado.id}/inscribirse"
        )
        assert r.status_code == 200

    def test_desapuntarse_sin_inscripcion_es_404(
        self, authenticated_client, make_voluntario, servicio_publicado
    ):
        make_voluntario(keycloak_id="test-user-id")
        r = authenticated_client.delete(
            f"{BASE}/{servicio_publicado.id}/inscribirse"
        )
        assert r.status_code == 404


class TestListarVoluntariosDeServicio:
    def test_jefe_puede_listar_voluntarios(
        self,
        jefe_client,
        servicio_publicado,
        make_voluntario,
        db_session,
    ):
        from datetime import datetime

        from app.models.inscripcion_servicio import (
            InscripcionServicio,
            TipoInscripcion,
        )

        ana = make_voluntario(nombre="Ana García")
        db_session.add(
            InscripcionServicio(
                servicio_id=servicio_publicado.id,
                voluntario_id=ana.id,
                tipo=TipoInscripcion.INSCRITO,
                fecha=datetime(2026, 5, 27, 10, 0),
            )
        )
        db_session.commit()

        r = jefe_client.get(f"{BASE}/{servicio_publicado.id}/voluntarios")
        assert r.status_code == 200
        nombres = [v["nombre"] for v in r.json()]
        assert "Ana García" in nombres

    def test_voluntario_basico_no_puede_listar(
        self, authenticated_client, servicio_publicado
    ):
        # `voluntario` no tiene `fichaje.ver_voluntarios_en_servicio`.
        r = authenticated_client.get(
            f"{BASE}/{servicio_publicado.id}/voluntarios"
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Matriz RBAC condensada (defensa documental del lockstep front/back)
# ---------------------------------------------------------------------------


class TestMatrizRbacResumida:
    """Cada permiso E03 va al rol correcto en endpoints reales."""

    def _payload_emergencia(self):
        return dict(
            titulo="Emergencia X",
            tipo="emergencia",
            fecha_inicio="2026-05-27T10:00:00",
            ubicacion="Zuera",
        )

    def test_tesorero_solo_lectura(
        self, client_for_role, servicio_publicado, voluntario
    ):
        c = client_for_role(["tesorero"])
        assert c.get(BASE).status_code == 200
        assert c.get(f"{BASE}/{servicio_publicado.id}").status_code == 200
        # Sin crear, ni publicar, ni convocar.
        assert (
            c.post(BASE, json={
                "titulo": "x",
                "tipo": "preventivo",
                "fecha_inicio": "2026-08-01T09:00:00",
                "ubicacion": "x",
            }).status_code == 403
        )
        assert (
            c.post(f"{BASE}/{servicio_publicado.id}/publicar").status_code == 403
        )

    def test_secretario_puede_crear_preventivo_pero_no_convocar(
        self, client_for_role, servicio_publicado, voluntario
    ):
        c = client_for_role(["secretario"])
        r = c.post(BASE, json={
            "titulo": "Preventivo formal",
            "tipo": "preventivo",
            "fecha_inicio": "2026-08-01T09:00:00",
            "ubicacion": "Zaragoza",
        })
        assert r.status_code == 201
        assert (
            c.post(
                f"{BASE}/{servicio_publicado.id}/convocar",
                json={"voluntario_ids": [str(voluntario.id)]},
            ).status_code == 403
        )

    def test_coordinador_puede_todo(
        self, client_for_role, servicio_borrador
    ):
        c = client_for_role(["coordinador"])
        # Publicar el borrador.
        r1 = c.post(f"{BASE}/{servicio_borrador.id}/publicar")
        assert r1.status_code == 200
        # Convocar.
        r2 = c.post(f"{BASE}/{servicio_borrador.id}/convocar")
        assert r2.status_code == 200
        # Cerrar.
        r3 = c.post(f"{BASE}/{servicio_borrador.id}/cerrar")
        assert r3.status_code == 200
