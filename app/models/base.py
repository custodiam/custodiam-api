"""Utilidades base para modelos SQLModel.

Funciones helper reutilizables para campos comunes:
- pk_uuid(): Primary key UUID4 generada en Python
- created_at_column(): Timestamp de creación (server_default)
- updated_at_column(): Timestamp de actualización (onupdate)
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, func
from sqlmodel import Field


def pk_uuid() -> uuid.UUID:
    """Columna UUID como primary key.

    Genera UUID4 en el lado Python (no en la BD).
    """
    return Field(default_factory=uuid.uuid4, primary_key=True)  # type: ignore[return-type]


def created_at_column() -> datetime | None:
    """Columna created_at con server_default=now().

    Se usa sa_column porque DateTime(timezone=True) y server_default
    no tienen equivalente directo en Field().
    """
    return Field(  # type: ignore[return-type]
        default=None,
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
    )


def updated_at_column() -> datetime | None:
    """Columna updated_at con server_default=now() y onupdate=now().

    Se actualiza automáticamente en cada UPDATE.
    """
    return Field(  # type: ignore[return-type]
        default=None,
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        ),
    )
