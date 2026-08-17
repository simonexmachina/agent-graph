+++
title = "Demo – trace a decision"
description = "Use the AgentGraph skill and AgentGraph CLI to trace a decision across a fictional Gmail thread, Slack discussion, Drive plan, and research documents."
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

Without AgentGraph, a coding agent would need separate integrations and authentication for each source. With the AgentGraph skill installed, it can use the CLI to discover the relevant entities, follow people and thread relationships, compare source dates, and return an answer with links.

## 1. Install AgentGraph and the AgentGraph skill

Install the published package with `uv`:

```bash
uv tool install agentgraph-server
agentgraph install-skill --target project --claude
```

The skill is installed in the local directory (in `.agents/skills` and `.claude/skills`).

## 2. Create an isolated demo database

We'll use a disposable config directory to create an isolated database for this demo.

```bash
echo 'AGENTGRAPH_CONFIG_DIR=/tmp/agentgraph-atlas-demo' > .env
agentgraph demo seed --config-dir /tmp/agentgraph-atlas-demo --reset
```

The fixture contains a set of Gmail, Slack, Drive, research, people, and relationship records. It is self-contained and does not call those services.

## 3. Ask your coding agent

Open a coding-agent session and give it this prompt:

> Use the AgentGraph skill to answer this question: Before I reply to Maya, reconstruct the Atlas synchronization decision. What did she require, what did engineering agree, does this match the plan on Drive, and which research supports the decision? Flag contradictions and link every source.

The coding agent should use the installed AgentGraph skill and commands such as `agentgraph search`, `agentgraph get`, and `agentgraph traverse` to gather context from the different sources.

## 4. Open the viewer

In a second terminal, stay in the temporary demo directory and start the local server:

```bash
agentgraph serve
```

Then open [http://127.0.0.1:8765/viewer](http://127.0.0.1:8765/viewer). The viewer shows the same seeded Atlas entities and relationships that the coding agent investigated.

## 5. Expected evidence

The answer should identify:

- Maya's five-minute synchronization requirement and September 30 deadline from Gmail;
- engineering's decision to use webhook delivery with idempotent consumers from Slack;
- the Drive plan's stale hourly-batch proposal and conflicting October 15 date;
- the Reliable Webhooks article's advice on idempotency and replay; and
- the vendor retry guide's exponential backoff, jitter, and dead-letter guidance.

Every claim should identify and link its source. The answer should distinguish facts stated in the sources from conclusions formed by comparing them.

To configure AgentGraph for your own sources, continue with [Install](/install.html).
