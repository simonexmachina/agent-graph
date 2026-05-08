---
# agent-graph-ot2v
title: Add platform filter to search_entities_tool
status: completed
type: feature
priority: normal
created_at: 2026-05-04T16:26:46Z
updated_at: 2026-05-04T16:29:48Z
---

Thread platform: str | None = None from search_entities_tool → graph/query.py → StorageBackend ABC → both backends. Add --platform flag to CLI search command for parity. Update SKILL.md.

## Summary of Changes

Threaded `platform: str | None = None` through the full search stack:
- `StorageBackend.search_entities` ABC — added `platform` keyword param
- SQLite `search_entities` — added `AND e.platform = ?` to FTS5 query; passed to `vector_ranked`
- SQLite `vector_ranked` — added `AND platform = ?` to all vector WHERE clauses
- Postgres `search_entities` — added `AND platform = $N` to type_filter for both CTEs
- `graph/query.py` `search_entities` — new `platform` param forwarded to backend
- `server/cli_api.py` `/search` — new `platform` query param
- `mcp/server.py` `search_entities_tool` — new `platform` param with docstring
- `cli.py` `search` command — added `--platform / -p` option
- `cli_query.py` `cmd_search` — new `platform` param, passed to server and local fallback
- `SKILL.md` — updated search command signature
- Tests: 2 new tests in `test_query.py` verifying platform is forwarded
