# Repository Guidelines

## Project Structure & Module Organization

`ffpanel/` contains the Python 3.12 FastAPI backend; backend tests live in `tests/`. The Vue 3 and TypeScript client is under `web/`, with application code in `web/src/` and Vitest files colocated as `*.test.ts`. Database migrations belong in `alembic/versions/`. Deployment files include `docker/`, `Dockerfile`, and `docker-compose.yml`; scripts are in `scripts/`, and design notes are in `docs/`. `openapi.json` is the committed API contract; generated frontend types live in `web/src/generated/`.

## Build, Test, and Development Commands

- `python -m pip install -e ".[dev]"` installs the backend and development tools.
- `uvicorn ffpanel.main:app --reload --port 8090` runs the backend locally.
- `pytest` runs all backend tests.
- `ruff check .` and `mypy ffpanel` run Python linting and strict type checks.
- `cd web && npm ci` installs the locked frontend dependencies.
- `cd web && npm run dev` starts Vite on port 5173 and proxies API traffic to port 8090.
- `cd web && npm test` runs Vitest; `npm run build` type-checks and builds production assets.
- `docker compose up -d --build` builds and starts the RK3588-oriented deployment.

## Coding Style & Naming Conventions

Use four-space indentation, type annotations, `snake_case` functions/modules, and `PascalCase` Python classes. Ruff enforces a 100-character line limit; keep code compatible with strict mypy. In TypeScript/Vue, use two spaces, single quotes, no semicolons, `camelCase` identifiers, and `PascalCase.vue` component names. Do not edit generated files manually.

## Testing Guidelines

Pytest uses automatic async support; name files `test_*.py` and tests `test_<behavior>`. Prefer temporary paths and `mock_media=True` instead of real FFmpeg or device access. Frontend tests use Vitest with jsdom and should sit beside the unit under test. No numeric coverage threshold is configured, but each behavior change should include regression coverage.

When changing public API schemas or routes, run `python scripts/export_openapi.py`, then `cd web && npm run api:generate`, and commit both contract updates.

## Commit & Pull Request Guidelines

Recent history uses short, descriptive Chinese summaries rather than Conventional Commit prefixes. Keep each commit focused and state the observable outcome. Pull requests should explain the motivation, list verification commands, call out migrations/configuration or API-contract changes, link relevant issues, and include screenshots for visible UI changes.

## Security & Configuration

Never commit `.env`, SQLite databases, `config/`, `cache/`, media, or `rclone.conf`. Keep `FFPANEL_LOCAL_ROOTS` narrowly scoped, and back up `config/` before applying Alembic migrations in deployed environments.
