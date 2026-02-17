"""Configuración de base de datos con SQLModel.

SQLModel unifica SQLAlchemy + Pydantic. La clase base es SQLModel (no DeclarativeBase).
La sesión se crea con Session de sqlmodel (no sessionmaker).
"""

from collections.abc import Generator

from sqlmodel import Session, create_engine

from app.core.config import settings

engine = create_engine(settings.database_url)


def get_session() -> Generator[Session, None, None]:
    """Generador de sesiones para inyección de dependencias en FastAPI.

    Uso en routers:
        @router.get("/voluntarios")
        def listar(session: Session = Depends(get_session)):
            ...
    """
    with Session(engine) as session:
        yield session
