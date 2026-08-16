# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

## Git Authority

- Commit each completed and validated logical unit as you work; do not wait until the end of the session.
- Keep implementation and its tests in the same commit.
- Stage only files that belong to the current task. Never include unrelated user changes in a commit.
- At successful session close, run the relevant quality gates and push the current branch. Direct pushes to the active branch, including `main`, are authorized unless the user or orchestrator says otherwise.
- If synchronization or push fails, do not force-push or use destructive recovery. Report the exact command and error.

## Server Lifecycle

- `agentgraph serve` is normally managed by the macOS LaunchAgent `com.agentgraph.server`. Do not start or stop it directly; use `launchctl kickstart` when a restart is required.
- Exception: when `.env` contains an uncommented `AGENTGRAPH_CONFIG_DIR`, the user is running an isolated test server manually in a terminal. Do not use launchd to start, stop, or restart the server in that mode; leave lifecycle control to the user.

## Documentation Website

- In this repository, “website” means the public documentation site hosted on GitHub Pages, built from `docs-src/` and previewed with `uv run python scripts/serve_docs.py` at `http://127.0.0.1:8001/`.
- The local `agentgraph serve` endpoint and its `/viewer` route are the graph viewer, not the public website.

## Build & Test

_Add your build and test commands here_

```bash
# Example:
# npm install
# npm test
```

## Architecture Overview

_Add a brief overview of your project architecture_

## Conventions & Patterns

_Add your project-specific conventions here_
