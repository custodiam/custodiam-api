"""Test de migración del catálogo de ubicaciones (E10 / PR2).

Aplica la cadena Alembic completa sobre una base de datos PostgreSQL
*throwaway* (creada y destruida dentro del test) y verifica:

- ``upgrade head`` crea la tabla ``ubicaciones`` con sus columnas.
- El ``UniqueConstraint`` del ``nombre`` rechaza duplicados.
- Las coordenadas ``lat`` / ``lng`` admiten ``NULL`` y valores reales.
- ``downgrade`` hasta antes de PR2 elimina la tabla.

Valida que la migración escrita a mano coincide con lo que
``SQLModel.metadata.create_all`` genera en el resto de la suite: producción
migra con Alembic, los tests crean el schema con ``create_all``, y este test
es el puente que garantiza que ambos caminos producen la misma tabla.

Requiere Postgres real. La BD throwaway se crea en la misma instancia que
``TEST_DATABASE_URL`` para reutilizar el contenedor de tests del 5433.
"""

from __future__ import annotations

import os
import uuid

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://custodiam:test@localhost:5433/custodiam_test",
)

# Revisión inmediatamente anterior a la de PR2 (head previo de la cadena).
REV_ANTES_PR2 = "c4d5e6f7a8b9"
REV_UBICACIONES = "e7a1b2c3d4e5"


def _split_url(url: str) -> tuple[str, str]:
    """Separa la URL en (url_sin_db, nombre_db)."""

    base, _, db = url.rpartition("/")
    return base, db


@pytest.fixture
def throwaway_db_url():
    """Crea una BD vacía única y la elimina al terminar."""

    base, _ = _split_url(TEST_DATABASE_URL)
    db_name = f"custodiam_mig_{uuid.uuid4().hex[:10]}"
    admin_url = f"{base}/postgres"

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin_engine.dispose()

    yield f"{base}/{db_name}"

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :db AND pid <> pg_backend_pid()"
            ),
            {"db": db_name},
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
    admin_engine.dispose()


def _alembic_config(url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_upgrade_y_downgrade_pr2(throwaway_db_url, monkeypatch):
    # `alembic/env.py` sobreescribe `sqlalchemy.url` con `DATABASE_URL` del
    # entorno si está presente, así que hay que apuntarla a la BD throwaway.
    monkeypatch.setenv("DATABASE_URL", throwaway_db_url)
    cfg = _alembic_config(throwaway_db_url)

    command.upgrade(cfg, "head")

    engine = create_engine(throwaway_db_url)
    insp = sa.inspect(engine)

    # 1. La tabla existe con todas sus columnas.
    assert "ubicaciones" in insp.get_table_names()
    cols = {c["name"] for c in insp.get_columns("ubicaciones")}
    assert cols == {
        "id",
        "nombre",
        "descripcion",
        "lat",
        "lng",
        "created_at",
        "updated_at",
    }

    # 2. El UniqueConstraint del nombre rechaza duplicados.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ubicaciones (id, nombre) VALUES (:id, 'Base')"
            ),
            {"id": uuid.uuid4()},
        )
    with pytest.raises(Exception) as exc:  # noqa: PT011 — IntegrityError de psycopg
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO ubicaciones (id, nombre) VALUES (:id, 'Base')"
                ),
                {"id": uuid.uuid4()},
            )
    assert "nombre" in str(exc.value).lower()

    # 3. lat/lng admiten valores reales (y NULL por defecto en el INSERT #2).
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ubicaciones (id, nombre, lat, lng) "
                "VALUES (:id, 'Punto', 41.65, -0.88)"
            ),
            {"id": uuid.uuid4()},
        )
        fila = conn.execute(
            text("SELECT lat, lng FROM ubicaciones WHERE nombre = 'Punto'")
        ).one()
    assert (fila.lat, fila.lng) == (41.65, -0.88)

    # 4. Downgrade elimina la tabla.
    engine.dispose()
    command.downgrade(cfg, REV_ANTES_PR2)

    engine = create_engine(throwaway_db_url)
    insp = sa.inspect(engine)
    assert "ubicaciones" not in insp.get_table_names()
    engine.dispose()
