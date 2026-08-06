+++
title = "Quickstart"
description = "Get AgentGraph indexing quickly with the shortest useful path."
nav_title = "Quickstart"
section = "Start"
order = 30
summary = "This page assumes the repo is already cloned and dependencies are installed. The goal is one working local graph, not a full production setup."
output = "quickstart.html"
source_path = "docs-src/quickstart.md"
+++

This quickstart uses the default SQLite backend so you can get to a working graph with the fewest moving parts.

## 1. Authenticate

Run the guided onboarding flow:

```bash
agentgraph onboard
```

If you only want one source, authenticate it directly with `agentgraph auth <source>`.

## 2. Start AgentGraph

```bash
agentgraph serve
```

The default server URL is `http://127.0.0.1:8765`.

## 3. Browse something supported

Open a Slack channel, a Google Doc, a Google Sheet, a Gmail thread, or a Drive folder. Leave the tab focused long enough for the dwell threshold to trigger a fetch.

For RSS, add a feed URL. AgentGraph validates it and queues a background poll:

```bash
agentgraph connector rss add https://example.com/feed.xml
```

## 4. Verify entities landed

```bash
agentgraph connectors --json
agentgraph search "slack" --limit 5
agentgraph query --type Document --limit 5
```

## 5. Connect an assistant

```bash
agentgraph mcp-config
```

Use the printed stdio config in Claude Desktop or Claude Code. For ChatGPT developer mode, run AgentGraph with streamable HTTP, expose the local `/mcp` endpoint through HTTPS, and create an app/connector using that public `/mcp` URL.
