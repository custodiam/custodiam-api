# Custodiam API

Backend API para gestión de agrupaciones de Protección Civil.

## Stack

- Python 3.11+
- FastAPI
- SQLAlchemy 2.0
- PostgreSQL 15

## Desarrollo

```bash
# Crear entorno virtual
python3 -m venv venv
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Ejecutar en desarrollo
uvicorn app.main:app --reload --port 8000

# Tests
pytest tests/ -v

# Linter
ruff check app/ tests/
```

## Variables de entorno

Copia `.env.example` a `.env` y ajusta los valores:

```bash
cp .env.example .env
```

## Swagger UI

Una vez ejecutando: http://localhost:8000/docs

## Repos relacionados

- [custodiam-app](https://github.com/custodiam/custodiam-app) — App Flutter
- [custodiam-infra](https://github.com/custodiam/custodiam-infra) — Docker y configuraciones

## Licencia

AGPL-3.0 — Ver [LICENSE](./LICENSE)
