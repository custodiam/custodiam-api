# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.routers import (
    auth,
    disponibilidad,
    dispositivos,
    fichajes,
    inventario,
    roles,
    servicios,
    voluntarios,
)

app = FastAPI(
    title="Custodiam API",
    description="API para gestión de agrupaciones de Protección Civil",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — en producción se restringe a dominios conocidos
allowed_origins = ["*"] if settings.debug else [
    "https://app.custodiam.es",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    """Endpoint raíz con info básica."""
    return {
        "status": "ok",
        "app": "Custodiam API",
        "version": "0.1.0",
    }


@app.get("/health")
def health():
    """Healthcheck para Docker y monitorización."""
    return {"status": "healthy"}


app.include_router(auth.router, prefix=f"/api/{settings.api_version}")
app.include_router(roles.router, prefix=f"/api/{settings.api_version}")
app.include_router(voluntarios.router, prefix=f"/api/{settings.api_version}")
app.include_router(servicios.router, prefix=f"/api/{settings.api_version}")
app.include_router(fichajes.router, prefix=f"/api/{settings.api_version}")
app.include_router(fichajes.self_router, prefix=f"/api/{settings.api_version}")
app.include_router(inventario.router, prefix=f"/api/{settings.api_version}")
app.include_router(
    inventario.servicio_router, prefix=f"/api/{settings.api_version}"
)
app.include_router(dispositivos.router, prefix=f"/api/{settings.api_version}")
app.include_router(disponibilidad.router, prefix=f"/api/{settings.api_version}")
