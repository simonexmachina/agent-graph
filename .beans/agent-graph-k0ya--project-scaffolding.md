---
# agent-graph-k0ya
title: Project scaffolding
status: completed
type: task
priority: normal
created_at: 2026-03-24T10:18:53Z
updated_at: 2026-03-24T10:53:57Z
parent: agent-graph-szbj
---

Set up Python project (uv/pyproject.toml). Directory structure: server/, connectors/, graph/, mcp/, extension/. Config loading (env vars + config file). Logging setup. Pyright in strict mode (pyrightconfig.json). pytest with markers: unit (default) and integration (skipped unless -m integration). conftest.py with DB fixtures for integration tests.

## Summary of Changes

- uv project initialised with Python 3.12
- Dependencies: fastapi, uvicorn, asyncpg, pydantic-settings, sentence-transformers, typer, rich, apscheduler, google-auth stack, httpx
- Dev dependencies: pytest, pytest-asyncio, pyright
- Directory structure: agentgraph/ (config, logging, cli, cli_query, auth/, server/), tests/
- pyproject.toml: pytest markers (unit/integration), asyncio_mode=auto, pyright strict config
- Settings class via pydantic-settings with AGENTGRAPH_ env prefix
- CLI skeleton: serve, auth google-docs, auth slack, search, get, edges, traverse, query
- 6 passing unit tests, 0 pyright errors
