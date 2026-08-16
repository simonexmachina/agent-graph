+++
title = "AgentGraph"
description = "AgentGraph is a local-first CLI and MCP server that turns selected digital sources into a searchable graph for the AI agent you already use."
nav_title = "Overview"
section = "Start"
order = 10
summary = ""
output = "index.html"
source_path = "docs-src/index.md"
+++

<div class="home-intro">
  <p class="positioning">AgentGraph is a local-first, self-hosted CLI and MCP server that turns the sources you choose into a graph of messages, documents, people, feeds, pages, and relationships for your agent to use for reasoning.</p>
</div>

<div class="home-actions">
  <a class="primary" href="/demo.html">See the demo</a>
  <a href="/quickstart.html">Quickstart</a>
  <a href="https://github.com/simonexmachina/agent-graph">GitHub</a>
</div>

Coding agents work well because their source of truth is already available on disk. They can search files, follow references, inspect history, and build a model of a system. AgentGraph applies that advantage to the selected digital context outside the current repository.

## Connectors

Connectors define which selected services and URLs AgentGraph can access. Some use
provider authentication, while others use connector-owned configuration or require no
credentials. Connecting a source is setup; its context lifecycle then has four paths:

- **Observe:** when you keep a supported page focused, the Chrome extension tells the local server which resource mattered and its connector fetches it.
- **Fetch:** an agent or the CLI requests a specific missing or stale resource directly.
- **Refresh:** polling keeps known resources updated as they change.
- **Expiry:** content is expired using a [retention model](/retention.html).

## What the agent can perceive

AgentGraph provides a number of connectors for common services, but new connectors can also be added to allow integration with other services. Teams, individuals, and open-source contributors can extend AgentGraph to include internal systems, niche tools, exports, local databases, and APIs.

| Connector | What it contributes |
| --- | --- |
| Gmail | Email threads, participants, subjects, bodies, and attachment references |
| Google Drive, Docs, Sheets | Folders, files, content, ownership, authorship, and containment |
| Slack | Channels and DMs, messages, replies, authors, mentions, and attachments |
| Discord | Channels, DMs, threads, messages, authors, mentions, and attachments |
| RSS | Feeds, posts, dates, authors, and publication relationships |
| Web | Configured pages and bookmarks with titles, text, metadata, and URLs |

<div class="connector-promise"><strong>Bring any service into your agent's world.</strong> Use the bundled connectors today, then add other connectors to build the context your own agent needs.</div>

[Explore connectors](/connectors.html) or [build your own](/extending.html).

## Start here

<div class="doc-card-grid">
  <section class="doc-card">
    <h3><a href="/quickstart.html">Quickstart</a></h3>
    <p>Install AgentGraph, observe one source, connect MCP, and ask the first useful question.</p>
  </section>
  <section class="doc-card">
    <h3><a href="/how-it-works.html">How it works</a></h3>
    <p>Understand observation, direct fetch, refresh, the graph model, and local data flow.</p>
  </section>
  <section class="doc-card">
    <h3><a href="/connectors.html">Connectors</a></h3>
    <p>See current coverage and how the open connector architecture expands to other services.</p>
  </section>
  <section class="doc-card">
    <h3><a href="/retention.html">Retention</a></h3>
    <p>Learn how observations, ownership, graph connections, expiration, and bookmarks interact.</p>
  </section>
  <section class="doc-card">
    <h3><a href="/commands/">CLI reference</a></h3>
    <p>Search, query, fetch, observe, poll, run connector commands, and operate the local graph.</p>
  </section>
  <section class="doc-card">
    <h3><a href="/mcp/">MCP tools</a></h3>
    <p>Connect an existing agent to search, traversal, fetch, and graph-management tools.</p>
  </section>
</div>

## Local by design

Indexed content is stored in SQLite on your machine. Source API calls run from your machine under your credentials. The project does not operate a hosted graph service or receive indexed content through a project-controlled backend.

An MCP client you connect can read content from the local graph and is governed by that client's data practices. Read the [Privacy Policy](/privacy.html), [Terms of Service](/terms.html), and [retention model](/retention.html).
