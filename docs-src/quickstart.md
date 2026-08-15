+++
title = "Quickstart"
description = "Install AgentGraph, observe one source, connect an existing agent over MCP, and ask the first useful question."
nav_title = "Quickstart"
section = "Start"
order = 30
summary = "The success condition is not merely that entities landed: your existing agent should answer a question using local AgentGraph context and link the source entities it used."
output = "quickstart.html"
source_path = "docs-src/quickstart.md"
+++

This path uses the default local SQLite backend and the bundled connectors.

## 1. Install

AgentGraph requires Python 3.12 or later and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/simonexmachina/agent-graph
cd agent-graph
uv sync --extra all
source .venv/bin/activate
```

Activating `.venv` makes the `agentgraph` command available in the current shell. Alternatively, prefix commands with `uv run`.

See [Install](/install.html) for connector-specific dependency groups and background-service configuration.

## 2. Connect a source

Run guided onboarding for authenticated services:

```bash
agentgraph onboard
```

You can authenticate one provider with `agentgraph auth <source>`. RSS and generic Web do not require provider credentials:

```bash
agentgraph connector rss add https://example.com/feed.xml
agentgraph connector web add 'https://example.com/research/*'
```

## 3. Start the local server

```bash
agentgraph serve
```

The server listens at `http://127.0.0.1:8765`. It accepts browser observations, runs connector pollers, serves the viewer, and exposes the local HTTP backend.

## 4. Observe one resource

Install the [AgentGraph Chrome extension](https://chromewebstore.google.com/detail/agentgraph-extension/iilkfclglabllelhjacijldknapbhidi). Open a supported Slack channel, Discord channel, Gmail thread, Google Doc, Sheet, Drive folder, RSS article, or configured web page. Keep it focused past the default three-second observation threshold.

The extension reports the recognized resource to your local server. Its connector fetches the resource and stores its entities, people, and edges before the observation is accepted.

## 5. Verify useful context

```bash
agentgraph connectors
agentgraph query --since 15m --limit 10
agentgraph search "a phrase from the resource" --limit 5
```

Open `http://127.0.0.1:8765/viewer` to inspect the entity, relationships, source link, and `observed_at` timestamp.

## 6. Connect the agent you already use

```bash
agentgraph mcp-config
```

Use the printed stdio configuration with Claude Desktop, Claude Code, Codex, or another compatible MCP client. ChatGPT developer mode requires `agentgraph mcp-serve --transport streamable-http`, an HTTPS endpoint ending in `/mcp`, and the corresponding app or connector configuration.

## 7. Ask a source-backed question

Ask the agent for something that requires the context you just observed:

> Use AgentGraph to explain the latest decision in the resource I just viewed. Follow relevant people and references, distinguish source facts from your inference, and link the source entities you used.

The agent should call AgentGraph search, get, and traversal tools rather than ask you to paste the source. If a result points to a missing or stale resource, it can call `fetch_entity_tool` or `fetch_entity_by_id_tool` to add or refresh it directly.

For a credential-free, repeatable cross-source scenario, run the [Trace a decision demo](/demo.html).

## What happened

- Browser observation marked a resource as relevant and triggered a targeted connector fetch.
- The connector translated source-specific data into local entities, people, and edges.
- MCP exposed that graph to your existing agent.
- Direct agent fetch remains distinct from human observation and does not update `observed_at`.

Continue with [How AgentGraph works](/how-it-works.html), [Connectors](/connectors.html), and [Entity retention](/retention.html).
