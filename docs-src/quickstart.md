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

This quickstart assumes the default SQLite backend so you can get to a working graph with the fewest moving parts. If you prefer PostgreSQL, switch after the first run with the steps in [PostgreSQL](/postgresql.html).

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

## 3. Install the browser extension

Download the latest `agentgraph-extension.zip` release asset, unzip it, and load the extracted `dist/` folder as an unpacked Chrome extension.

If you prefer to build it locally instead:

```bash
cd extension
npm install
npm run build
```

## 4. Browse something supported

Open a Slack channel, a Google Doc, a Google Sheet, a Gmail thread, or a Drive folder. Leave the tab focused long enough for the dwell threshold to trigger a fetch.

## 5. Verify entities landed

```bash
agentgraph connectors --json
agentgraph search "slack" --limit 5
agentgraph query --type Document --limit 5
```

## 6. Connect an assistant

```bash
agentgraph mcp-config
```

Use the printed config in Claude Desktop or Claude Code, or expose SSE / streaming HTTP for ChatGPT developer mode.
