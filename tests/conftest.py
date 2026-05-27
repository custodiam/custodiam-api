"""Configuración global de pytest para custodiam-api.

Estrategia de testing (cerrada en `docs/trabajo/conceptual/09_CALIDAD`):

- **Base de datos:** PostgreSQL real, separada de la de producción.
  La URL se toma de `TEST_DATABASE_URL` (default `postgresql+psycopg://
  custodiam:test@localhost:5433/custodiam_test`). El docker-compose de
  `custodiam-infra` no la levanta: el operador la arranca aparte vía
  ``docker run --rm -d --name custodiam-db-test -p 5433:5432
  -e POSTGRES_USER=custodiam -e POSTGRES_PASSWORD=test
  -e POSTGRES_DB=custodiam_test postgres:16-alpine``.
- **Schema:** se recrea una vez al inicio de la sesión con
  ``SQLModel.metadata.create_all``. Los catálogos extensibles
  (`tipos_acreditacion`, `tipos_equipamiento`, `roles`) se siembran con
  un set mínimo y se mantienen toda la sesión.
- **Aislamiento entre tests:** TRUNCATE de las tablas operativas tras
  cada test. Los catálogos sobreviven.

Las fixtures de cliente HTTP (`client`, `authenticated_client`,
`admin_client`, `jefe_client`, `client_for_role`) sobrescriben
`get_session` para que los routers usen la misma BD de tests.
"""

import os
import uuid
from collections.abc import Generator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlmodel import Session, SQLModel

import app.models  # noqa: F401 -- registra modelos en SQLModel.metadata
from app.core.database import get_session
from app.core.security import get_current_user
from app.main import app
from app.models.rol import Rol
from app.models.tipo_acreditacion import CategoriaAcreditacion, TipoAcreditacion
from app.models.tipo_equipamiento import TipoEquipamiento
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

    Crea el schema completo desde `SQLModel.metadata` y siembra los
    catálogos mínimos. No ejecuta migraciones de Alembic: la cobertura
    de migraciones se delega al smoke test de EN-08-38 (Sprint 5).
    """

    engine = create_engine(TEST_DATABASE_URL, echo=False)

    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        _seed_catalogos(session)
        session.commit()

    yield engine

    engine.dispose()


def _seed_catalogos(session: Session) -> None:
    """Siembra el set mínimo de catálogos que usan los tests.

    Refleja una porción representativa del seed real de la migración
    `08460f65687b`. No es exhaustivo: solo lo que los tests necesitan
    para crear instancias de Acreditacion, TallaVoluntario y VoluntarioRol.
    """

    session.add_all([
        TipoAcreditacion(
            id=uuid.uuid4(),
            codigo="carnet_b",
            nombre="Carnet de conducir B",
            categoria=CategoriaAcreditacion.LICENCIA_OFICIAL,
            activo=True,
        ),
        TipoAcreditacion(
            id=uuid.uuid4(),
            codigo="primeros_auxilios",
            nombre="Primeros auxilios",
            categoria=CategoriaAcreditacion.FORMACION_INTERNA,
            activo=True,
        ),
    ])

    session.add_all([
        TipoEquipamiento(
            id=uuid.uuid4(),
            codigo="camisa",
            nombre="Camisa de servicio",
            sistema_tallas="XS-XXXL",
            activo=True,
        ),
        TipoEquipamiento(
            id=uuid.uuid4(),
            codigo="botas",
            nombre="Botas operativas",
            sistema_tallas="36-50",
            activo=True,
        ),
    ])

    session.add_all([
        Rol(id=uuid.uuid4(), nombre="voluntario", nivel=1),
        Rol(id=uuid.uuid4(), nombre="jefe_equipo", nivel=3),
        Rol(id=uuid.uuid4(), nombre="jefe_agrupacion", nivel=8),
        Rol(id=uuid.uuid4(), nombre="coordinador", nivel=9),
    ])


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
        self.roles_asignados.append((keycloak_id, role_name))

    def quitar_rol_realm(  # type: ignore[override]
        self, keycloak_id: str, role_name: str
    ) -> None:
        self.roles_revocados.append((keycloak_id, role_name))


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
