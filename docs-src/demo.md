+++
title = "Demo – trace a decision"
description = "Use the Graph skill and AgentGraph CLI to trace a decision across a fictional Gmail thread, Slack discussion, Drive plan, and research documents."
nav_title = "Demo"
section = "Start"
order = 60
summary = "Install the AgentGraph skill, create a fictional graph, and let a coding agent investigate a decision by searching and traversing it with the AgentGraph CLI."
output = "demo.html"
source_path = "docs-src/demo.md"
+++

This demo investigates a technical decision from a fictional Gmail thread, Slack discussion, Drive plan, and two research documents. Everything is included in a static fixture, so the demo focuses on cross-source search, graph traversal, and evidence-backed reasoning.

## The question

> Before I reply to Maya, reconstruct the Atlas synchronization decision. What did she require, what did engineering agree, does the Drive plan match, and which research supports the decision? Flag contradictions and link every source.

Without AgentGraph, a coding agent would need separate integrations and authentication for each source. With the Graph skill installed, it can use one local CLI to discover the relevant entities, follow people and thread relationships, compare source dates, and return an answer with links.

## 1. Install AgentGraph and the Graph skill

Install the published package with `uv`:

```bash
uv tool install --reinstall agentgraph-server==0.5.2
agentgraph install-skill graph --target user
```

The skill is installed at `~/.agents/skills/graph/SKILL.md`. Open a new coding-agent session after installation so it discovers the skill. If that destination already contains an older AgentGraph Graph skill, re-run the second command with `--force` to deliberately replace it.

## 2. Create an isolated demo graph

Choose a disposable config directory. The command refuses the default `~/.agentgraph` directory and refuses to overwrite an existing demo database unless `--reset` is supplied. It also refuses to replace a non-demo `.env` file.

```bash
agentgraph demo seed --config-dir /tmp/agentgraph-atlas-demo --reset
```

The fixture contains all Gmail, Slack, Drive, research, people, and relationship records. It is self-contained and does not call those services.

## 3. Start the local backend

In a dedicated terminal, start AgentGraph against the fixture:

```bash
AGENTGRAPH_CONFIG_DIR=/tmp/agentgraph-atlas-demo \
  agentgraph serve
```

This is the local backend used by the CLI. The demo does not require provider credentials, the browser extension, or a research-page web server.

## 4. Ask a coding agent

Then give your coding agent this prompt:

> Use the Graph skill and AgentGraph CLI to answer this question: Before I reply to Maya, reconstruct the Atlas synchronization decision. What did she require, what did engineering agree, does the Drive plan match, and which research supports the decision? Flag contradictions and link every source.

The coding agent should use the installed Graph skill and commands such as `agentgraph search --json`, `agentgraph get --json`, and `agentgraph traverse --json`. It should not read the SQLite database directly or ask you to configure source credentials.

## Expected evidence

The answer should identify:

- Maya's five-minute synchronization requirement and September 30 deadline from Gmail;
- engineering's decision to use webhook delivery with idempotent consumers from Slack;
- the Drive plan's stale hourly-batch proposal and conflicting October 15 date;
- the Reliable Webhooks article's advice on idempotency and replay; and
- the vendor retry guide's exponential backoff, jitter, and dead-letter guidance.

Every claim should identify and link its source. The answer should distinguish facts stated in the sources from conclusions formed by comparing them.

## Recording sequence

1. Show the package installation and fixture seed completing with entity, person, and edge counts.
2. Install the Graph skill and open a coding-agent session.
3. Ask the demo question with the local AgentGraph server running.
4. Keep the CLI calls visible as the agent searches, opens entities, and traverses relationships.
5. End on the concise evidence-backed answer with links to each source.

Label the fixture as fictional in the recording and description. The goal is reproducibility, not the appearance of private production data.
