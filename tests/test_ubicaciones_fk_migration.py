"""Test de migración del enganche inventario ↔ ubicaciones (E10 / PR2).

Aplica la cadena Alembic completa sobre una BD PostgreSQL *throwaway* y
verifica la revisión ``f1a2b3c4d5e6``:

- ``upgrade head`` añade ``ubicacion_base_id`` (FK) a ``materiales`` y
  ``vehiculos`` y relaja ``ubicacion_base`` a nullable.
- Un material sin ``ubicacion_base`` (solo posible tras la migración) se
  inserta sin error.
- El FK rechaza un ``ubicacion_base_id`` que no existe en el catálogo.
- El ``ON DELETE RESTRICT`` impide borrar una ubicación en uso.
- ``downgrade`` revierte columnas, FK e índices y re-impone el ``NOT NULL``.

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

# Revisión inmediatamente anterior al enganche (catálogo ya creado).
REV_SOLO_CATALOGO = "e7a1b2c3d4e5"


def _split_url(url: str) -> tuple[str, str]:
    base, _, db = url.rpartition("/")
    return base, db


@pytest.fixture
def throwaway_db_url():
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


def _insert_material(conn, *, ubicacion_base_id=None) -> uuid.UUID:
    mat_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO materiales "
            "(id, nombre, tipo, estado, cantidad, ubicacion_base_id) "
            "VALUES (:id, 'Botiquín', 'PRESTABLE', 'OPERATIVO', 1, :ubi)"
        ),
        {"id": mat_id, "ubi": ubicacion_base_id},
    )
    return mat_id


def test_upgrade_y_downgrade_pr2_fk(throwaway_db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", throwaway_db_url)
    cfg = _alembic_config(throwaway_db_url)

    command.upgrade(cfg, "head")

    engine = create_engine(throwaway_db_url)
    insp = sa.inspect(engine)

    # 1. La columna FK existe en ambas tablas y `ubicacion_base` es nullable.
    for tabla in ("materiales", "vehiculos"):
        cols = {c["name"]: c for c in insp.get_columns(tabla)}
        assert "ubicacion_base_id" in cols
        assert cols["ubicacion_base"]["nullable"] is True
        fks = {fk["referred_table"] for fk in insp.get_foreign_keys(tabla)}
        assert "ubicaciones" in fks

    # 2. Un material sin etiqueta de texto (solo posible tras PR2) entra bien.
    with engine.begin() as conn:
        _insert_material(conn)  # ubicacion_base NULL, ubicacion_base_id NULL

    # 3. El FK rechaza un ubicacion_base_id inexistente.
    with pytest.raises(Exception) as exc:  # noqa: PT011 — IntegrityError de psycopg
        with engine.begin() as conn:
            _insert_material(conn, ubicacion_base_id=uuid.uuid4())
    assert "ubicacion_base_id" in str(exc.value).lower() or "foreign" in str(
        exc.value
    ).lower()

    # 4. ON DELETE RESTRICT: no se borra una ubicación en uso.
    with engine.begin() as conn:
        ubi_id = uuid.uuid4()
        conn.execute(
            text("INSERT INTO ubicaciones (id, nombre) VALUES (:id, 'Base')"),
            {"id": ubi_id},
        )
        _insert_material(conn, ubicacion_base_id=ubi_id)
    with pytest.raises(Exception) as exc:  # noqa: PT011 — IntegrityError de psycopg
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM ubicaciones WHERE id = :id"), {"id": ubi_id}
            )
    assert "restrict" in str(exc.value).lower() or "foreign" in str(exc.value).lower()

    # 5. Downgrade: limpiar las filas para poder re-imponer el NOT NULL.
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM materiales"))
        conn.execute(text("DELETE FROM ubicaciones"))
    engine.dispose()
    command.downgrade(cfg, REV_SOLO_CATALOGO)

    engine = create_engine(throwaway_db_url)
    insp = sa.inspect(engine)
    for tabla in ("materiales", "vehiculos"):
        cols = {c["name"]: c for c in insp.get_columns(tabla)}
        assert "ubicacion_base_id" not in cols
        assert cols["ubicacion_base"]["nullable"] is False
    engine.dispose()
