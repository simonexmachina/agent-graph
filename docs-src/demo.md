+++
title = "Trace a decision demo"
description = "Run the reproducible AgentGraph launch demo across Gmail, Slack, Drive, browser observation, and an agent-initiated web fetch."
nav_title = "Demo"
section = "Start"
order = 60
summary = "Use a fictional Atlas project to demonstrate cross-source reasoning without exposing private data. The fixture is static; browser observation and MCP fetch are live."
output = "demo.html"
source_path = "docs-src/demo.md"
+++

The launch demo reconstructs one technical decision from a fictional Gmail thread, Slack discussion, Drive plan, and two web research pages. It is designed to prove cross-source search and traversal, browser observation, agent-initiated fetch, and evidence-backed reasoning in one short story.

## The question

> Before I reply to Maya, reconstruct the Atlas synchronization decision. What did she require, what did engineering agree, does the Drive plan match, and which research supports the decision? Flag contradictions and link every source.

Without AgentGraph, a coding agent cannot inspect those sources. With AgentGraph connected over MCP, it can discover the relevant entities, traverse people and thread relationships, fetch missing context, compare source dates, and return an answer with links.

## 1. Create an isolated demo graph

Choose a disposable config directory. The seed script refuses the default `~/.agentgraph` directory and refuses to overwrite an existing demo database unless `--reset` is supplied.

```bash
uv run python scripts/seed_launch_demo.py --config-dir /tmp/agentgraph-atlas-demo --reset
```

Start AgentGraph against that directory:

```bash
AGENTGRAPH_CONFIG_DIR=/tmp/agentgraph-atlas-demo uv run agentgraph serve
```

The fixture contains the Gmail, Slack, Drive, people, and relationship records. It does not contain the two web pages.

## 2. Serve the research pages

In another terminal:

```bash
uv run python -m http.server 8899 --directory demo/atlas-web
```

Configure the generic Web connector to recognize those pages:

```bash
AGENTGRAPH_CONFIG_DIR=/tmp/agentgraph-atlas-demo \
  uv run agentgraph connector web add 'http://127.0.0.1:8899/*'
```

## 3. Observe the first article

Install the Chrome extension and point it at `http://127.0.0.1:8765`. Open `http://127.0.0.1:8899/reliable-webhooks.html` and keep the tab focused past the observation threshold.

The extension reports the recognized URL to the local server. The Web connector fetches the page, stores it as a `Document`, and records `observed_at`.

## 4. Connect an agent

Print the MCP configuration while working in the project environment:

```bash
AGENTGRAPH_CONFIG_DIR=/tmp/agentgraph-atlas-demo uv run agentgraph mcp-config
```

Add the printed configuration to the coding agent you already use, and add this `env` entry beside its `command` and `args` fields:

```json
"env": {
  "AGENTGRAPH_CONFIG_DIR": "/tmp/agentgraph-atlas-demo"
}
```

Then ask the demo question. The Slack discussion links to `retry-guidance.html`, which is not yet in the graph. The agent should call `fetch_entity_tool("web", "http://127.0.0.1:8899/retry-guidance.html")` before finishing its answer.

## Expected evidence

The answer should identify:

- Maya's five-minute synchronization requirement and September 30 deadline from Gmail;
- engineering's decision to use webhook delivery with idempotent consumers from Slack;
- the Drive plan's stale hourly-batch proposal and conflicting October 15 date;
- the observed webhook article's advice on idempotency and replay; and
- the directly fetched retry guide's exponential backoff and dead-letter guidance.

Every claim should link to its source entity. The observed article should have `observed_at` set. The directly fetched retry guide should have `observed_at = null`, demonstrating that agent fetch is not recorded as human attention.

## Recording sequence

1. Ask the question before connecting AgentGraph and show the agent explaining that it cannot inspect the sources.
2. Show the extension recognizing and observing the webhook article.
3. Connect the isolated AgentGraph MCP server and ask the same question.
4. Keep the MCP tool calls visible as the agent searches, traverses, and fetches the missing retry guide.
5. End on the evidence-backed answer and the viewer's observation timestamps.

Label the fixture as fictional in the recording and description. The goal is reproducibility, not the appearance of private production data.
