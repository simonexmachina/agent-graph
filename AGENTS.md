## Committing

Commit incrementally as you complete each logical unit of work — don't batch everything into one commit at the end.

## Questions and Changes

When the user asks a question, answer it without changing code unless they explicitly request implementation or a fix is an unambiguously necessary improvement.

## CLI / MCP / Skill Parity

Whenever a CLI command is added or changed (`agentgraph/cli.py`, `agentgraph/cli_query.py`), apply the equivalent change to the MCP server (`agentgraph/mcp/server.py`) and update the `/graph` skill (`.claude/skills/graph/SKILL.md`) in the same pass. All three must stay in sync.

## Shell / Scripting

- **Use `jq` for JSON parsing** in shell scripts and one-liners — prefer it over Python for command-line JSON manipulation.

## Logs

- Treat `/tmp/agentgraph.log` as the default server log file location when inspecting runtime errors for this repo.

## Server Lifecycle

- `agentgraph serve` is managed by the macOS LaunchAgent `com.agentgraph.server`. Do not start or stop it directly; use `launchctl kickstart` when a restart is required.

## Chrome Extension Publishing

- Publish the Chrome extension only through the GitHub Actions `Extension Release` workflow. Do not upload builds through the Chrome Web Store dashboard.
- A version bump in `extension/manifest.json`, `extension/package.json`, and `extension/package-lock.json`, followed by a pushed `v*` tag, triggers the release. The workflow creates the GitHub Release and publishes the ZIP to Chrome Web Store.
- The repository requires `CWS_CLIENT_ID`, `CWS_CLIENT_SECRET`, and `CWS_REFRESH_TOKEN` Actions secrets for Chrome Web Store publishing.

## Connector / Core Boundary

Connector-specific logic must live in the connector package (`packages/agentgraph-connector-*/`), not in the main `agentgraph/` package. Violations to watch for:

- **Hardcoded platform names** in `agentgraph/graph/`, `agentgraph/backends/`, or `agentgraph/server/` (outside `server/router.py`). If you're checking `if platform == "slack"` in core code, it belongs in the connector.
- **Platform metadata field names** accessed directly in the main package (e.g. `metadata["slack_user_id"]`, `metadata["gmail_message_id"]`). Connectors own their metadata schema.
- **Hardcoded platform lists** in CLI, migration, or UI code (e.g. `["slack", "gmail", "discord"]`). Use the connector registry to discover platforms dynamically.
- **Importing connector modules** from within `agentgraph/` core code.

The correct pattern: connectors expose standardised interfaces (`BaseConnector` methods, `EntityBatch` output, `resolve_me()` hook) that core code calls generically. If you need platform-specific behaviour, add a hook to `BaseConnector` that the connector overrides.

When a connector needs behaviour that core does not currently provide, treat that as an architectural decision. Ask the human how to provide the needed capability while preserving separation of concerns instead of adding connector-specific branches or commands to core. Prefer generic core extension points, such as connector-owned command hooks, where the connector package owns parsing and behaviour and core only dispatches through the registry.

## Development Standards

- **Write tests as you go.** Every feature bean gets tests in the same commit. Unit tests for pure logic; integration tests (marked `@pytest.mark.integration`) for anything touching the database or external APIs. Integration tests are skipped by default (`pytest -m "not integration"`).
- **Strongly typed Python.** All code uses type hints throughout — function signatures, return types, class attributes. Pydantic models at all data boundaries. Pyright in strict mode for static checking.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:970c3bf2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   bd dolt push
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

<!-- BEGIN BEADS CODEX SETUP: generated by bd setup codex -->
## Beads Issue Tracker

Use Beads (`bd`) for durable task tracking in repositories that include it. Use the `beads` skill at `.agents/skills/beads/SKILL.md` (project install) or `~/.agents/skills/beads/SKILL.md` (global install) for Beads workflow guidance, then use the `bd` CLI for issue operations.

### Quick Reference

```bash
bd ready                # Find available work
bd show <id>            # View issue details
bd update <id> --claim  # Claim work
bd close <id>           # Complete work
bd prime                # Refresh Beads context
```

### Rules

- Use `bd` for all task tracking; do not create markdown TODO lists.
- Run `bd prime` when Beads context is missing or stale. Codex 0.129.0+ can load Beads context automatically through native hooks; use `/hooks` to inspect or toggle them.
- Keep persistent project memory in Beads via `bd remember`; do not create ad hoc memory files.

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.
<!-- END BEADS CODEX SETUP -->
