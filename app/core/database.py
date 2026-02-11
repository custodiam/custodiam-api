# app/core/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Clase base para todos los modelos SQLAlchemy."""

    pass


def get_db():
    """Dependency injection para obtener sesión de BD."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
