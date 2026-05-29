"""Test de migración de PR3 (dotación fija de material a vehículo).

Aplica la cadena Alembic completa sobre una base de datos PostgreSQL
*throwaway* (creada y destruida dentro del test) y verifica:

- ``upgrade head`` aplica las dos revisiones de PR3 sin error.
- El valor de enum ``DOTACION_VEHICULO`` queda disponible.
- La columna ``vehiculo_id`` y el CHECK ternario existen y funcionan
  (rechaza 2 targets, acepta dotación pura).
- ``downgrade`` hasta antes de PR3 revierte columna, FK y CHECK ternario
  dejando el CHECK binario original; el valor de enum sobrevive
  (PostgreSQL no soporta DROP VALUE).

Requiere Postgres real (``::int`` y ``ALTER TYPE`` no existen en SQLite).
La BD throwaway se crea en la misma instancia que ``TEST_DATABASE_URL``
para reutilizar el contenedor de tests del 5433.
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

# Revisión inmediatamente anterior a la primera de PR3.
REV_ANTES_PR3 = "6ac94c20a63b"
REV_ENUM = "a1b2c3d4e5f6"
REV_COLUMNA = "b2c3d4e5f6a1"


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


def test_upgrade_y_downgrade_pr3(throwaway_db_url, monkeypatch):
    # `alembic/env.py` sobreescribe `sqlalchemy.url` con `DATABASE_URL` del
    # entorno si está presente, así que hay que apuntarla a la BD throwaway.
    monkeypatch.setenv("DATABASE_URL", throwaway_db_url)
    cfg = _alembic_config(throwaway_db_url)

    # Aplicar toda la cadena hasta head (incluye las dos revisiones PR3).
    command.upgrade(cfg, "head")

    engine = create_engine(throwaway_db_url)
    insp = sa.inspect(engine)

    # 1. Columna vehiculo_id presente.
    cols = {c["name"] for c in insp.get_columns("asignaciones_material")}
    assert "vehiculo_id" in cols

    # 2. Índice de vehiculo_id presente.
    indexes = {i["name"] for i in insp.get_indexes("asignaciones_material")}
    assert "ix_asignaciones_material_vehiculo_id" in indexes

    # 3. Valor de enum DOTACION_VEHICULO disponible.
    with engine.connect() as conn:
        labels = conn.execute(
            text(
                "SELECT e.enumlabel FROM pg_enum e "
                "JOIN pg_type t ON t.oid = e.enumtypid "
                "WHERE t.typname = 'tipo_asignacion_material'"
            )
        ).scalars().all()
    assert "DOTACION_VEHICULO" in labels

    # 4. CHECK ternario funciona: necesitamos un material y un vehículo
    #    reales por las FK. Insertamos lo mínimo con SQL crudo.
    with engine.begin() as conn:
        mat_id = uuid.uuid4()
        veh_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO materiales "
                "(id, nombre, tipo, estado, cantidad, ubicacion_base) "
                "VALUES (:id, 'Botiquín', 'PRESTABLE', 'OPERATIVO', 1, 'Base')"
            ),
            {"id": mat_id},
        )
        conn.execute(
            text(
                "INSERT INTO vehiculos "
                "(id, codigo_interno, matricula, tipo, estado, ubicacion_base) "
                "VALUES (:id, 'VH-MIG-1', '0000-AAA', 'FURGONETA', "
                "'OPERATIVO', 'Base')"
            ),
            {"id": veh_id},
        )

    # 4a. Dotación pura (sólo vehiculo_id) → aceptada.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO asignaciones_material "
                "(id, material_id, vehiculo_id, tipo, cantidad, fecha_asignacion) "
                "VALUES (:id, :mat, :veh, 'DOTACION_VEHICULO', 1, now())"
            ),
            {"id": uuid.uuid4(), "mat": mat_id, "veh": veh_id},
        )

    # 4b. Dos targets (servicio + vehiculo) → rechazada por el CHECK.
    with pytest.raises(Exception) as exc:  # noqa: PT011 — IntegrityError de psycopg
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO asignaciones_material "
                    "(id, material_id, vehiculo_id, servicio_id, tipo, "
                    "cantidad, fecha_asignacion) "
                    "VALUES (:id, :mat, :veh, :srv, 'DOTACION_VEHICULO', "
                    "1, now())"
                ),
                {
                    "id": uuid.uuid4(),
                    "mat": mat_id,
                    "veh": veh_id,
                    "srv": uuid.uuid4(),
                },
            )
    assert "ck_asignacion_material_target" in str(exc.value)

    # 5. Downgrade hasta antes de PR3. El downgrade recrea el CHECK binario
    #    (sólo voluntario/servicio), que es incompatible con cualquier fila
    #    de dotación viva (vehiculo_id set, resto NULL = 0 targets bajo el
    #    binario). Un operador real tendría que liberar/migrar esas filas
    #    antes de bajar; lo replicamos borrándolas.
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM asignaciones_material "
                "WHERE tipo = 'DOTACION_VEHICULO'"
            )
        )
    engine.dispose()
    command.downgrade(cfg, REV_ANTES_PR3)

    engine = create_engine(throwaway_db_url)
    insp = sa.inspect(engine)
    cols = {c["name"] for c in insp.get_columns("asignaciones_material")}
    assert "vehiculo_id" not in cols

    # El valor de enum NO se elimina en downgrade (PG no soporta DROP VALUE).
    with engine.connect() as conn:
        labels = conn.execute(
            text(
                "SELECT e.enumlabel FROM pg_enum e "
                "JOIN pg_type t ON t.oid = e.enumtypid "
                "WHERE t.typname = 'tipo_asignacion_material'"
            )
        ).scalars().all()
    assert "DOTACION_VEHICULO" in labels

    engine.dispose()
