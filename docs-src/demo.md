+++
title = "Demo – trace a decision"
description = "Use the Graph skill and AgentGraph CLI to trace a decision across a fictional Gmail thread, Slack discussion, Drive plan, and research documents."
nav_title = "Demo"
section = "Start"
order = 60
summary = "Seed one isolated fictional graph, install the Graph skill, and let a coding agent reconstruct a decision by searching and traversing with the AgentGraph CLI."
output = "demo.html"
source_path = "docs-src/demo.md"
+++

The launch demo reconstructs one technical decision from a fictional Gmail thread, Slack discussion, Drive plan, and two research documents. Everything is included in a static fixture, so the demo focuses on cross-source search, graph traversal, and evidence-backed reasoning.

## The question

> Before I reply to Maya, reconstruct the Atlas synchronization decision. What did she require, what did engineering agree, does the Drive plan match, and which research supports the decision? Flag contradictions and link every source.

Without AgentGraph, a coding agent would need separate integrations and authentication for each source. With the Graph skill installed, it can use one local CLI to discover the relevant entities, follow people and thread relationships, compare source dates, and return an answer with links.

## 1. Install the Graph skill

From the AgentGraph repository, install dependencies and the bundled skill:

```bash
uv sync --extra all
uv run agentgraph install-skill graph --target user --force
```

The skill is installed at `~/.agents/skills/graph/SKILL.md`. The `--force` flag refreshes only that installed Graph skill. Restart the coding agent after installation so it discovers the current version.

## 2. Create an isolated demo graph

Choose a disposable config directory. The seed script refuses the default `~/.agentgraph` directory and refuses to overwrite an existing demo database unless `--reset` is supplied.

```bash
uv run python scripts/seed_launch_demo.py --config-dir /tmp/agentgraph-atlas-demo --reset
```

The fixture contains all Gmail, Slack, Drive, research, people, and relationship records. It is self-contained and does not call those services.

## 3. Start the local CLI server

In a dedicated terminal, start AgentGraph against the fixture using full-text search only:

```bash
AGENTGRAPH_CONFIG_DIR=/tmp/agentgraph-atlas-demo \
AGENTGRAPH_BACKEND_SQLITE_VECTOR_MODE=bm25-only \
  uv run agentgraph serve
```

This server is the local backend used by the CLI. The demo does not require an MCP configuration, provider credentials, the browser extension, or a research-page web server.

## 4. Ask a coding agent

Start or restart your coding agent from the repository with the virtual environment on `PATH`:

```bash
export PATH="$PWD/.venv/bin:$PATH"
```

Then give it this prompt:

> Use the Graph skill and AgentGraph CLI to answer this question: Before I reply to Maya, reconstruct the Atlas synchronization decision. What did she require, what did engineering agree, does the Drive plan match, and which research supports the decision? Flag contradictions and link every source.

The coding agent should use commands such as `agentgraph search --json`, `agentgraph get --json`, and `agentgraph traverse --json`. It should not read the SQLite database directly or ask you to configure source credentials.

## Expected evidence

The answer should identify:

- Maya's five-minute synchronization requirement and September 30 deadline from Gmail;
- engineering's decision to use webhook delivery with idempotent consumers from Slack;
- the Drive plan's stale hourly-batch proposal and conflicting October 15 date;
- the Reliable Webhooks article's advice on idempotency and replay; and
- the vendor retry guide's exponential backoff, jitter, and dead-letter guidance.

Every claim should identify and link its source. The answer should distinguish facts stated in the sources from conclusions formed by comparing them.

## Recording sequence

1. Show the fixture seed completing with entity, person, and edge counts.
2. Install the Graph skill and restart the coding agent.
3. Ask the demo question with the local AgentGraph server running.
4. Keep the CLI calls visible as the agent searches, opens entities, and traverses relationships.
5. End on the concise evidence-backed answer with links to each source.

Label the fixture as fictional in the recording and description. The goal is reproducibility, not the appearance of private production data.
