"""Configuración global de pytest para custodiam-api.

Estrategia de testing (cerrada en `docs/trabajo/conceptual/09_CALIDAD`):

- **Base de datos:** PostgreSQL real, separada de la de producción.
  La URL se toma de `TEST_DATABASE_URL` (default `postgresql+psycopg://
  custodiam:test@localhost:5433/custodiam_test`). La instancia la levanta
  el flavor de test del compose de `custodiam-infra` (`just test-up`):
  servicio `db-test` efímero (tmpfs, `postgres:15-alpine`), aislado de la
  BD de desarrollo.
- **Schema:** se recrea al inicio de la sesión aplicando las MIGRACIONES de
  Alembic (`upgrade head`) sobre un schema limpio (`DROP SCHEMA public`), no
  `create_all`. Así la suite valida el schema REAL de producción (detecta
  drift modelos↔migraciones) y los catálogos (`tipos_acreditacion`,
  `tipos_equipamiento`, `roles`) los siembran las propias migraciones de
  datos, sin duplicar el seed a mano.
- **Aislamiento entre tests:** TRUNCATE de las tablas operativas tras
  cada test. Los catálogos sobreviven.

Las fixtures de cliente HTTP (`client`, `authenticated_client`,
`admin_client`, `jefe_client`, `client_for_role`) sobrescriben
`get_session` para que los routers usen la misma BD de tests.
"""

import os
from collections.abc import Generator
from datetime import date

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlmodel import Session

import app.models  # noqa: F401 -- registra modelos en SQLModel.metadata
from app.core.database import get_session
from app.core.security import get_current_user
from app.main import app
from app.schemas.auth import CurrentUser
from app.services.keycloak_admin import KeycloakAdminClient, get_keycloak_admin

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://custodiam:test@localhost:5433/custodiam_test",
)


# Tablas que se limpian entre tests. NO incluye los catálogos ni `roles`
# (que también es catálogo, no estado operativo). Mantenerlas seeded
# evita reseeding caro en cada test.
_OPERATIONAL_TABLES = (
    "voluntario_eventos",
    "notificaciones",
    "dispositivos",
    "asignaciones_vehiculo",
    "asignaciones_material",
    "vehiculos",
    "materiales",
    "ubicaciones",
    "fichajes",
    "inscripciones_servicio",
    "servicios",
    "disponibilidades",
    "acreditaciones",
    "tallas_voluntario",
    "contactos_emergencia",
    "voluntario_roles",
    "voluntarios",
)


@pytest.fixture(scope="session")
def test_engine():
    """Engine compartido para toda la sesión de tests.

    Resetea el schema y aplica las MIGRACIONES de Alembic (`upgrade head`),
    no `create_all`: así la suite valida el schema real de producción (un
    drift entre los modelos y las migraciones se manifiesta aquí) y los
    catálogos los siembran las propias migraciones de datos (`f76feacaf399`
    roles, `08460f65687b` tipos), sin duplicar el seed a mano.
    """

    engine = create_engine(TEST_DATABASE_URL, echo=False)

    # Reset total del schema (incluida la tabla `alembic_version`) para que
    # las migraciones partan de cero en cada sesión sobre el db-test efímero
    # del compose.
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.commit()

    _apply_migrations()

    yield engine

    engine.dispose()


def _apply_migrations() -> None:
    """Aplica `alembic upgrade head` sobre `TEST_DATABASE_URL`.

    `alembic/env.py` sobreescribe `sqlalchemy.url` con `DATABASE_URL` del
    entorno si está presente, así que se apunta ahí; `alembic.ini` se
    resuelve relativo al cwd (la raíz de `custodiam-api`, desde donde pytest
    se invoca).
    """

    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(cfg, "head")


@pytest.fixture
def db_session(test_engine) -> Generator[Session, None, None]:
    """Sesión SQLModel para un test. Trunca las tablas operativas al final."""

    with Session(test_engine) as session:
        yield session

    with test_engine.connect() as conn:
        # RESTART IDENTITY no aplica a UUID pero el flag es inocuo.
        conn.execute(
            text(
                f"TRUNCATE TABLE {', '.join(_OPERATIONAL_TABLES)} "
                "RESTART IDENTITY CASCADE"
            )
        )
        conn.commit()


class FakeFcmAdmin:
    """Sustituto sin red para `FcmAdminClient` en tests.

    No hereda de :class:`FcmAdminClient` para no arrastrar el ciclo de
    carga del service account; expone la misma interfaz pública
    (``enabled`` y ``enviar``) que el código de producción consume. Las
    llamadas se registran en ``envios`` para que los tests puedan
    asertar el fan-out.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        tokens_invalidos: set[str] | None = None,
        tokens_5xx: set[str] | None = None,
    ) -> None:
        self._enabled = enabled
        self.tokens_invalidos = tokens_invalidos or set()
        self.tokens_5xx = tokens_5xx or set()
        self.envios: list[dict] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enviar(self, *, token, titulo, cuerpo, prioridad, data=None):
        if token in self.tokens_5xx:
            from app.services.fcm_admin import FcmAdminError

            raise FcmAdminError(f"fake 5xx para token={token}")
        self.envios.append(
            {
                "token": token,
                "titulo": titulo,
                "cuerpo": cuerpo,
                "prioridad": prioridad,
                "data": data,
            }
        )
        if token in self.tokens_invalidos:
            return False
        return True


class FakeNtfyClient:
    """Sustituto sin red para `NtfyClient` en tests."""

    def __init__(self, *, enabled: bool = True, fail: bool = False) -> None:
        self._enabled = enabled
        self._fail = fail
        self.publicaciones: list[dict] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enviar(self, *, titulo, cuerpo, prioridad, topic=None, tags=None):
        if self._fail:
            from app.services.ntfy_client import NtfyError

            raise NtfyError("fake ntfy 5xx")
        self.publicaciones.append(
            {
                "titulo": titulo,
                "cuerpo": cuerpo,
                "prioridad": prioridad,
                "topic": topic,
                "tags": list(tags) if tags else None,
            }
        )
        return True


class FakeKeycloakAdmin(KeycloakAdminClient):
    """Sustituto sin red para `KeycloakAdminClient` en tests.

    Mantiene la misma firma pública para que los routers no distingan
    entre el cliente real y el fake. Registra todas las llamadas en
    listas internas para que los tests puedan asertar.
    """

    def __init__(self, *, fail_on: set[str] | None = None) -> None:
        # No llamamos a `super().__init__()` para no abrir sesión httpx.
        self._fail_on = fail_on or set()
        self.usuarios_creados: list[dict] = []
        self.usuarios_desactivados: list[str] = []
        self.roles_asignados: list[tuple[str, str]] = []
        self.roles_revocados: list[tuple[str, str]] = []
        self.emails_enviados: list[dict] = []
        self._next_kc_id = 1

    @property
    def enabled(self) -> bool:  # type: ignore[override]
        return True

    def crear_usuario(  # type: ignore[override]
        self,
        *,
        username: str,
        email: str | None,
        given_name: str,
        family_name: str,
        password_temporal: str | None = None,
    ) -> str | None:
        if "crear" in self._fail_on:
            from app.services.keycloak_admin import KeycloakAdminError

            raise KeycloakAdminError("fake_crear")
        kc_id = f"kc-fake-{self._next_kc_id:04d}"
        self._next_kc_id += 1
        self.usuarios_creados.append(
            {
                "id": kc_id,
                "username": username,
                "email": email,
                "given_name": given_name,
                "family_name": family_name,
            }
        )
        return kc_id

    def desactivar_usuario(self, keycloak_id: str) -> None:  # type: ignore[override]
        if "desactivar" in self._fail_on:
            from app.services.keycloak_admin import KeycloakAdminError

            raise KeycloakAdminError("fake_desactivar")
        self.usuarios_desactivados.append(keycloak_id)

    def asignar_rol_realm(  # type: ignore[override]
        self, keycloak_id: str, role_name: str
    ) -> None:
        if "rol" in self._fail_on:
            from app.services.keycloak_admin import KeycloakAdminError

            raise KeycloakAdminError("fake_asignar_rol")
        self.roles_asignados.append((keycloak_id, role_name))

    def quitar_rol_realm(  # type: ignore[override]
        self, keycloak_id: str, role_name: str
    ) -> None:
        self.roles_revocados.append((keycloak_id, role_name))

    def execute_actions_email(  # type: ignore[override]
        self,
        keycloak_id: str,
        *,
        actions: list[str] | None = None,
        client_id: str | None = None,
        lifespan_seconds: int | None = None,
    ) -> None:
        if "email" in self._fail_on:
            from app.services.keycloak_admin import KeycloakAdminError

            raise KeycloakAdminError("fake_execute_actions_email")
        self.emails_enviados.append(
            {
                "keycloak_id": keycloak_id,
                "actions": actions or ["VERIFY_EMAIL", "UPDATE_PASSWORD"],
                "client_id": client_id,
                "lifespan_seconds": lifespan_seconds,
            }
        )


@pytest.fixture
def fake_keycloak_admin() -> FakeKeycloakAdmin:
    """Instancia compartida por el TestClient durante un test."""

    return FakeKeycloakAdmin()


@pytest.fixture
def client(db_session, fake_keycloak_admin) -> Generator[TestClient, None, None]:
    """TestClient con `get_session` y `get_keycloak_admin` aislados."""

    def _override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_keycloak_admin] = lambda: fake_keycloak_admin
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _make_fake_user(
    sub: str = "test-user-id",
    email: str = "test@custodiam.es",
    preferred_username: str = "testuser",
    roles: list[str] | None = None,
    given_name: str = "Test",
    family_name: str = "User",
) -> CurrentUser:
    return CurrentUser(
        sub=sub,
        email=email,
        preferred_username=preferred_username,
        roles=roles or ["voluntario"],
        given_name=given_name,
        family_name=family_name,
    )


def _override_with_user(**user_kwargs):
    app.dependency_overrides[get_current_user] = lambda: _make_fake_user(**user_kwargs)


@pytest.fixture
def authenticated_client(client) -> TestClient:
    """Cliente autenticado como voluntario (rol único)."""

    _override_with_user()
    return client


@pytest.fixture
def admin_client(client) -> TestClient:
    """Cliente autenticado como admin + coordinador (admin del piloto)."""

    _override_with_user(
        sub="admin-user-id",
        email="admin@custodiam.es",
        preferred_username="admin",
        roles=["admin", "coordinador"],
        given_name="Admin",
        family_name="Custodiam",
    )
    return client


@pytest.fixture
def jefe_client(client) -> TestClient:
    """Cliente autenticado como jefe_equipo + voluntario."""

    _override_with_user(
        sub="jefe-user-id",
        email="jefe@custodiam.es",
        preferred_username="cjefe",
        roles=["jefe_equipo", "voluntario"],
        given_name="Carlos",
        family_name="López",
    )
    return client


@pytest.fixture
def client_for_role(client):
    """Factoría para autenticar el TestClient como un rol arbitrario.

    Útil en los tests de matriz RBAC, donde un mismo test cruza todos
    los roles contra un mismo endpoint.
    """

    def _factory(roles: list[str], *, sub: str | None = None) -> TestClient:
        _override_with_user(
            sub=sub or f"user-{'-'.join(roles)}",
            preferred_username="-".join(roles),
            roles=roles,
        )
        return client

    return _factory


# ---------------------------------------------------------------------------
# Factories de dominio
# ---------------------------------------------------------------------------


@pytest.fixture
def make_voluntario(db_session):
    """Crea un voluntario en BD con valores por defecto sensatos."""

    def _factory(
        *,
        nombre: str = "Ana García",
        telefono: str = "+34600000000",
        municipio: str = "Zaragoza",
        fecha_nacimiento: date = date(1990, 5, 12),
        dni: str | None = None,
        email: str | None = None,
        keycloak_id: str | None = None,
        fecha_alta: date = date(2026, 1, 1),
        **extra,
    ):
        from app.models.voluntario import Voluntario

        vol = Voluntario(
            nombre=nombre,
            telefono=telefono,
            municipio=municipio,
            fecha_nacimiento=fecha_nacimiento,
            dni=dni,
            email=email,
            keycloak_id=keycloak_id,
            fecha_alta=fecha_alta,
            **extra,
        )
        db_session.add(vol)
        db_session.commit()
        db_session.refresh(vol)
        return vol

    return _factory


@pytest.fixture
def voluntario(make_voluntario):
    """Voluntario por defecto, listo para usar en tests simples."""

    return make_voluntario()


@pytest.fixture
def make_servicio(db_session):
    """Crea un servicio en BD con valores por defecto sensatos."""

    from datetime import datetime as _dt

    from app.models.servicio import EstadoServicio, Servicio, TipoServicio

    def _factory(
        *,
        titulo: str = "Servicio de prueba",
        descripcion: str | None = None,
        tipo: TipoServicio = TipoServicio.PREVENTIVO,
        estado: EstadoServicio = EstadoServicio.BORRADOR,
        fecha_inicio: _dt = _dt(2026, 6, 1, 9, 0),
        fecha_fin: _dt | None = _dt(2026, 6, 1, 14, 0),
        ubicacion: str = "Zaragoza, Casco Histórico",
        numero_voluntarios: int | None = None,
        creado_por_keycloak_id: str | None = None,
        **extra,
    ):
        servicio = Servicio(
            titulo=titulo,
            descripcion=descripcion,
            tipo=tipo,
            estado=estado,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            ubicacion=ubicacion,
            numero_voluntarios=numero_voluntarios,
            creado_por_keycloak_id=creado_por_keycloak_id,
            **extra,
        )
        db_session.add(servicio)
        db_session.commit()
        db_session.refresh(servicio)
        return servicio

    return _factory


@pytest.fixture
def make_inscripcion(db_session):
    """Inserta una fila `InscripcionServicio` para un par (servicio, voluntario).

    Es la fuente de filas que alimenta `inscritos_count`. No reutiliza el
    repository para mantener la factoría independiente de la lógica de
    upsert (un test de conteo no debe depender de la promoción de tipos).
    """

    from datetime import datetime as _dt

    from app.models.inscripcion_servicio import InscripcionServicio, TipoInscripcion

    def _factory(
        *,
        servicio_id,
        voluntario_id,
        tipo: TipoInscripcion = TipoInscripcion.INSCRITO,
        fecha: _dt = _dt(2026, 6, 1, 10, 0),
    ):
        inscripcion = InscripcionServicio(
            servicio_id=servicio_id,
            voluntario_id=voluntario_id,
            tipo=tipo,
            fecha=fecha,
        )
        db_session.add(inscripcion)
        db_session.commit()
        db_session.refresh(inscripcion)
        return inscripcion

    return _factory


@pytest.fixture
def servicio_borrador(make_servicio):
    """Servicio en estado BORRADOR, listo para publicar / convocar."""

    return make_servicio()


@pytest.fixture
def servicio_publicado(make_servicio):
    """Servicio en estado PUBLICADO, listo para apuntarse o convocar."""

    from app.models.servicio import EstadoServicio

    return make_servicio(estado=EstadoServicio.PUBLICADO)


@pytest.fixture
def servicio_activo(make_servicio):
    """Servicio en estado ACTIVO, listo para fichar o cerrar."""

    from app.models.servicio import EstadoServicio

    return make_servicio(estado=EstadoServicio.ACTIVO)


# ---------------------------------------------------------------------------
# Factories de inventario (E05)
# ---------------------------------------------------------------------------


@pytest.fixture
def make_material(db_session):
    """Crea un Material con valores por defecto sensatos."""

    from app.models.material import EstadoInventario, Material, TipoMaterial

    counter = {"n": 0}

    def _factory(
        *,
        nombre: str = "Casco operativo",
        tipo: TipoMaterial = TipoMaterial.PERSONAL,
        estado: EstadoInventario = EstadoInventario.OPERATIVO,
        cantidad: int = 1,
        ubicacion_base: str = "Base PC Bajo Gállego",
        codigo: str | None = None,
        **extra,
    ):
        counter["n"] += 1
        if codigo is None:
            codigo = f"MAT-TEST-{counter['n']:04d}"
        material = Material(
            nombre=nombre,
            tipo=tipo,
            estado=estado,
            cantidad=cantidad,
            ubicacion_base=ubicacion_base,
            codigo=codigo,
            **extra,
        )
        db_session.add(material)
        db_session.commit()
        db_session.refresh(material)
        return material

    return _factory


@pytest.fixture
def material(make_material):
    return make_material()


@pytest.fixture
def make_vehiculo(db_session):
    """Crea un Vehiculo con valores por defecto sensatos."""

    from app.models.vehiculo import TipoVehiculo, Vehiculo

    counter = {"n": 0}

    def _factory(
        *,
        codigo_interno: str | None = None,
        matricula: str = "1234-ABC",
        tipo: TipoVehiculo = TipoVehiculo.FURGONETA,
        ubicacion_base: str = "Base PC Bajo Gállego",
        **extra,
    ):
        counter["n"] += 1
        if codigo_interno is None:
            codigo_interno = f"VH-TEST-{counter['n']:04d}"
        vehiculo = Vehiculo(
            codigo_interno=codigo_interno,
            matricula=matricula,
            tipo=tipo,
            ubicacion_base=ubicacion_base,
            **extra,
        )
        db_session.add(vehiculo)
        db_session.commit()
        db_session.refresh(vehiculo)
        return vehiculo

    return _factory


@pytest.fixture
def vehiculo(make_vehiculo):
    return make_vehiculo()


# ---------------------------------------------------------------------------
# Factories del catálogo de ubicaciones (E10)
# ---------------------------------------------------------------------------


@pytest.fixture
def make_ubicacion(db_session):
    """Crea una Ubicacion con valores por defecto sensatos.

    El nombre es único por defecto (counter) para no chocar con el
    constraint de unicidad cuando un test crea varias.
    """

    from app.models.ubicacion import Ubicacion

    counter = {"n": 0}

    def _factory(
        *,
        nombre: str | None = None,
        descripcion: str | None = None,
        lat: float | None = None,
        lng: float | None = None,
        **extra,
    ):
        counter["n"] += 1
        if nombre is None:
            nombre = f"Ubicación de prueba {counter['n']:04d}"
        ubicacion = Ubicacion(
            nombre=nombre,
            descripcion=descripcion,
            lat=lat,
            lng=lng,
            **extra,
        )
        db_session.add(ubicacion)
        db_session.commit()
        db_session.refresh(ubicacion)
        return ubicacion

    return _factory


@pytest.fixture
def ubicacion(make_ubicacion):
    return make_ubicacion()
