**IMPORTANT**: before you do anything else, run the `beans prime` command and heed its output.

## Committing

Commit incrementally as you complete each logical unit of work — don't batch everything into one commit at the end. Include related bean files in the same commit as the code changes they track.

## CLI / MCP / Skill Parity

Whenever a CLI command is added or changed (`agentgraph/cli.py`, `agentgraph/cli_query.py`), apply the equivalent change to the MCP server (`agentgraph/mcp/server.py`) and update the `/graph` skill (`.claude/skills/graph/SKILL.md`) in the same pass. All three must stay in sync.

## Shell / Scripting

- **Use `jq` for JSON parsing** in shell scripts and one-liners — prefer it over Python for command-line JSON manipulation.

## Connector / Core Boundary

Connector-specific logic must live in the connector package (`packages/agentgraph-connector-*/`), not in the main `agentgraph/` package. Violations to watch for:

- **Hardcoded platform names** in `agentgraph/graph/`, `agentgraph/backends/`, or `agentgraph/server/` (outside `server/router.py`). If you're checking `if platform == "slack"` in core code, it belongs in the connector.
- **Platform metadata field names** accessed directly in the main package (e.g. `metadata["slack_user_id"]`, `metadata["gmail_message_id"]`). Connectors own their metadata schema.
- **Hardcoded platform lists** in CLI, migration, or UI code (e.g. `["slack", "gmail", "discord"]`). Use the connector registry to discover platforms dynamically.
- **Importing connector modules** from within `agentgraph/` core code.

The correct pattern: connectors expose standardised interfaces (`BaseConnector` methods, `EntityBatch` output, `resolve_me()` hook) that core code calls generically. If you need platform-specific behaviour, add a hook to `BaseConnector` that the connector overrides.

## Development Standards

- **Write tests as you go.** Every feature bean gets tests in the same commit. Unit tests for pure logic; integration tests (marked `@pytest.mark.integration`) for anything touching the database or external APIs. Integration tests are skipped by default (`pytest -m "not integration"`).
- **Strongly typed Python.** All code uses type hints throughout — function signatures, return types, class attributes. Pydantic models at all data boundaries. Pyright in strict mode for static checking.