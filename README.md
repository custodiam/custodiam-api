# Custodiam API

Backend REST de **Custodiam**, sistema multiplataforma de gestión para agrupaciones de Protección Civil.

📚 **Documentación completa:** <https://docs.custodiam.es>

## Stack

- Python 3.13 (gestión automática vía [uv](https://docs.astral.sh/uv/))
- [FastAPI](https://fastapi.tiangolo.com/) — web framework
- [SQLModel](https://sqlmodel.tiangolo.com/) — ORM unificado (SQLAlchemy 2.0 + Pydantic)
- PostgreSQL 15 + [psycopg3](https://www.psycopg.org/psycopg3/) — BD relacional
- [Keycloak 26+](https://www.keycloak.org/) — IdP OIDC con OAuth2 + PKCE
- [PyJWT[crypto]](https://pyjwt.readthedocs.io/) — validación local de JWT
- [Alembic](https://alembic.sqlalchemy.org/) — migraciones de schema

## Desarrollo local

```bash
# Sincronizar el entorno (.venv/) con pyproject.toml + uv.lock (incluye extras dev)
uv sync --all-extras

# Configurar variables de entorno
cp .env.example .env
# Editar .env con valores reales o los del docker-compose del repo custodiam-infra

# Aplicar migraciones de BD
uv run alembic upgrade head

# Servidor de desarrollo con hot reload
uv run uvicorn app.main:app --reload --port 8000
```

Abre <http://localhost:8000/docs> para la documentación Swagger UI interactiva.

> Si `uv` no está instalado:
>
> - Linux/macOS: `curl -LsSf https://astral.sh/uv/install.sh | sh`
> - Windows: `winget install --id=astral-sh.uv` o `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

## Comandos esenciales

> **Prerrequisito de los tests:** la suite necesita el servicio `db-test` efímero
> del compose de `custodiam-infra`, levantado con `just test-up` (equivalente:
> `docker compose -f docker/docker-compose.yml -f docker/docker-compose.test.yml --profile test up -d --wait db-test`
> desde `custodiam-infra`). El `conftest` aplica `alembic upgrade head` sobre un
> schema limpio (`DROP SCHEMA`) y siembra los catálogos vía las migraciones de
> datos —valida el schema REAL de producción, no `create_all`—; apunta a
> `postgresql+psycopg://custodiam:test@localhost:5433/custodiam_test`.

```bash
# Tests + cobertura
uv run pytest tests/ -v
uv run pytest --cov=app --cov-report=term-missing

# Linter + formato
uv run ruff check app/ tests/
uv run ruff check --fix app/ tests/
uv run ruff format app/ tests/

# Migraciones Alembic
uv run alembic revision --autogenerate -m "descripción"
uv run alembic upgrade head
uv run alembic downgrade -1

# Añadir una dependencia (actualiza pyproject.toml + uv.lock)
uv add nombre-paquete            # runtime
uv add --dev nombre-paquete      # extras dev
```

> **Gotcha — `VIRTUAL_ENV` heredado:** si tu terminal hereda `VIRTUAL_ENV` de otro venv padre, `uv` lo respeta y NO usa el `.venv/` local del repo. Solución: `unset VIRTUAL_ENV` en cada terminal nueva.

## Estructura del repo

```text
custodiam-api/
├── app/
│   ├── core/              # config, database, security, permissions
│   ├── models/            # SQLModel (table=True)
│   ├── schemas/           # Pydantic para API
│   ├── routers/           # Endpoints REST agrupados
│   └── services/          # Lógica de negocio
├── alembic/               # Migraciones de schema
├── tests/                 # pytest con fixtures de cliente autenticado
├── pyproject.toml         # [project] PEP 621 + ruff + pytest config
├── uv.lock                # Lockfile reproducible
└── Dockerfile             # Multi-stage con builder uv + runtime python:slim
```

## Imagen Docker

`ghcr.io/custodiam/custodiam-api:latest` se construye y publica automáticamente al merge en `main` (workflow `build-docker`). Multi-stage con builder `ghcr.io/astral-sh/uv:0.9-python3.13-bookworm-slim` y runtime `python:3.13-slim-bookworm` para minimizar tamaño final.

## Más información

- **[docs.custodiam.es/empezar/api](https://docs.custodiam.es/empezar/api/)** — recorrido detallado de instalación con prerequisitos y troubleshooting.
- **[docs.custodiam.es/arquitectura](https://docs.custodiam.es/arquitectura/)** — diagramas del sistema, decisiones arquitectónicas, stack.
- **[docs.custodiam.es/adrs](https://docs.custodiam.es/adrs/)** — registro de decisiones (incl. uv adoption, RBAC, OAuth + PKCE web/móvil).
- **[docs.custodiam.es/contribuir](https://docs.custodiam.es/contribuir/)** — proceso de PR, código de conducta.

## Repos relacionados

- [custodiam-app](https://github.com/custodiam/custodiam-app) — App Flutter (Android + iOS + Web)
- [custodiam-infra](https://github.com/custodiam/custodiam-infra) — Docker Compose + Keycloak + scripts
- [custodiam-book](https://github.com/custodiam/custodiam-book) — Source del book de documentación pública

## Licencia

[AGPL-3.0](./LICENSE) — Ver el archivo LICENSE para el texto completo.
