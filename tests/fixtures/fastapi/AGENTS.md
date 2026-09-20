# FastAPI VibeOps Blueprint

## 1. Environment

- Python project managed with **uv** (NOT pip). Dependencies are locked in `uv.lock`.
- A Makefile wraps all common commands.
- Services run in Docker; the Dockerfile lives in the project root.

## 2. Architecture

- Layered architecture: Router → Service → Repository. Routers never touch the database.
- Use FastAPI dependency injection (`Depends()`) for all shared resources.
- The API is versioned under `/api/v1`.
- Async-first: all handlers and repository calls are `async def`.
- Configuration goes through Pydantic Settings (`BaseSettings`).
- Database migrations are managed with Alembic.
- The API contract is published as an OpenAPI spec file.
- SQLAlchemy 2.0 style models using `Mapped[...]`.
- Pydantic v2 only (`model_validate`, `model_dump`).

## 3. Security

- All endpoints are authenticated by default with JWT bearer tokens.
- Passwords are hashed with bcrypt.
- Role-based access control (RBAC) protects admin routes.
- No secrets in source. `.env` is in .gitignore.

## 4. Testing

- Unit tests in `tests/unit/`.
- Integration tests in `tests/integration/`.
- BDD with Gherkin `.feature` files (pytest-bdd).
- Shared fixtures live in `conftest.py`.
- Never skip tests or delete tests to make CI pass.

## 5. Code Quality

- Lint and format with ruff.
- Static typing with mypy.

## 6. Spec Adherence

- Spec-first: technical designs live in `specs/`.
- ADRs record architecture decisions.
- Conventional commits.

## 7. Layout

```
├── src/
│   ├── api/
│   │   └── v1/
│   ├── services/
│   ├── repositories/
│   └── core/
│       └── security.py
├── tests/
└── Makefile
```
