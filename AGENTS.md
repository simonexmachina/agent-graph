**IMPORTANT**: before you do anything else, run the `beans prime` command and heed its output.

## Committing

Commit incrementally as you complete each logical unit of work — don't batch everything into one commit at the end. Include related bean files in the same commit as the code changes they track.

## CLI / MCP / Skill Parity

Whenever a CLI command is added or changed (`agentgraph/cli.py`, `agentgraph/cli_query.py`), apply the equivalent change to the MCP server (`agentgraph/mcp/server.py`) and update the `/graph` skill (`.claude/skills/graph/SKILL.md`) in the same pass. All three must stay in sync.

## Shell / Scripting

- **Use `jq` for JSON parsing** in shell scripts and one-liners — prefer it over Python for command-line JSON manipulation.

## Development Standards

- **Write tests as you go.** Every feature bean gets tests in the same commit. Unit tests for pure logic; integration tests (marked `@pytest.mark.integration`) for anything touching the database or external APIs. Integration tests are skipped by default (`pytest -m "not integration"`).
- **Strongly typed Python.** All code uses type hints throughout — function signatures, return types, class attributes. Pydantic models at all data boundaries. Pyright in strict mode for static checking.