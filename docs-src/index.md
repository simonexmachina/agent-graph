+++
title = "AgentGraph documentation"
description = "AgentGraph docs home: install, quickstart, configuration, connectors, command reference, and MCP."
nav_title = "Overview"
section = "Start"
order = 10
summary = ""
output = "index.html"
source_path = "docs-src/index.md"
+++

AgentGraph builds a local, queryable graph of your digital world across tools like Slack, Discord, Gmail, Google Docs, Sheets, and Drive, so your AI agents can search, fetch, and reason over the same connected context you work from.

```bash
uv sync --extra all
agentgraph onboard
agentgraph serve
agentgraph mcp-config
```

You can also teach AgentGraph about new tools quickly: connectors live in their own packages, follow a small interface, and are straightforward to build with a coding agent. That makes it practical to extend the graph to internal tools, niche SaaS products, or one-off data sources without forking the core system.

## Where to start

<div class="doc-card-grid">
  <section class="doc-card">
    <h3><a href="/install.html">Install</a></h3>
    <p>Set up Python, sync dependencies, authenticate connectors, start the server, and connect the browser extension.</p>
  </section>
  <section class="doc-card">
    <h3><a href="/quickstart.html">Quickstart</a></h3>
    <p>Get to a working local graph fast: onboard, serve, browse a supported page, and verify the first entities landed.</p>
  </section>
  <section class="doc-card">
    <h3><a href="/configuration.html">Configuration</a></h3>
    <p>Choose the config directory, database path, retention window, dwell threshold, and transport settings.</p>
  </section>
  <section class="doc-card">
    <h3><a href="/postgresql.html">PostgreSQL</a></h3>
    <p>Move from the default SQLite setup to PostgreSQL when you want a separate database service.</p>
  </section>
  <section class="doc-card">
    <h3><a href="/extending.html">Extending</a></h3>
    <p>Learn how to extend AgentGraph with custom connectors for your own integrations, including the `BaseConnector` contract and example implementation.</p>
  </section>
  <section class="doc-card">
    <h3><a href="/commands/">Commands</a></h3>
    <p>Search, query, fetch, poll, auth, serve, and MCP. One reference surface for both terminal users and agent clients.</p>
  </section>
  <section class="doc-card">
    <h3><a href="/mcp/">MCP tools</a></h3>
    <p>One page per MCP tool for search, traversal, fetch, download, and connector inspection from agent clients.</p>
  </section>
</div>

## What AgentGraph does

- **Connectors:** turn messages, documents, spreadsheets, folders, and email threads into graph entities, people, and edges, and you can add your own.
- **Browser-driven capture:** watches supported URLs and triggers targeted fetches once you stay on a page long enough for it to matter.
- **Background refresh:** polls to keep already-known resources current after the first visit.
- **Shared interfaces:** the CLI, web viewer, and MCP server all operate on the same local graph.
- **Pluggable storage:** SQLite is the default local backend, and PostgreSQL is available when you want AgentGraph to use an external database service.

## Reference

- [Extending](/extending.html) for supported sources, custom connector development, and the `BaseConnector` interface reference.
- [PostgreSQL](/postgresql.html) for running AgentGraph against PostgreSQL instead of the default SQLite backend.
- [Commands](/commands/) for the CLI and MCP surface.
- [MCP tools](/mcp/) for the tool-by-tool agent interface reference.
- [Privacy](/privacy.html) for the local storage and browser observation model.

## Surfaces

<table>
  <thead>
    <tr>
      <th>Surface</th>
      <th>Use it for</th>
      <th>Entry point</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>CLI</td>
      <td>Ad hoc search, fetch, ingest, debugging, and operations.</td>
      <td><code>agentgraph search</code>, <code>agentgraph fetch</code>, <code>agentgraph serve</code></td>
    </tr>
    <tr>
      <td>MCP</td>
      <td>ChatGPT developer mode, Claude Desktop, Claude Code, and other MCP clients.</td>
      <td><code>agentgraph mcp-config</code>, <code>agentgraph mcp-serve</code></td>
    </tr>
    <tr>
      <td>Browser extension</td>
      <td>Passive indexing from supported browser tabs.</td>
      <td><code>extension/dist/</code> in Chrome Developer Mode</td>
    </tr>
    <tr>
      <td>Viewer</td>
      <td>Visual graph inspection and manual exploration.</td>
      <td><code>http://127.0.0.1:8765/viewer</code></td>
    </tr>
  </tbody>
</table>

## Get help

- File issues: [github.com/simonexmachina/agent-graph/issues](https://github.com/simonexmachina/agent-graph/issues)
- Source: [github.com/simonexmachina/agent-graph](https://github.com/simonexmachina/agent-graph)
- Privacy model: [Privacy](/privacy.html)
