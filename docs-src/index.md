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
  <p class="positioning"><strong>Give the AI agent you already use a searchable world.</strong> AgentGraph is a local-first, self-hosted CLI and MCP server that turns the sources you choose into a graph of messages, documents, people, feeds, pages, and relationships.</p>
  <p class="boundary"><strong>AgentGraph stores context; your agent reasons over it.</strong> It is not an agent, chatbot, or hosted graph service.</p>
</div>

<div class="home-actions">
  <a class="primary" href="/demo.html">See the demo</a>
  <a href="/quickstart.html">Quickstart</a>
  <a href="https://github.com/simonexmachina/agent-graph">GitHub</a>
</div>

Coding agents work well because their source of truth is already available on disk. They can search files, follow references, inspect history, and build a model of a system. AgentGraph applies that advantage to the selected digital context outside the current repository.

<figure class="architecture-figure">
  <img src="/assets/diagrams/architecture-overview-dark.svg" alt="Selected online services connect to AgentGraph on the user's machine. Browser observation, direct agent fetch, and background refresh flow through connector packages into a local graph exposed through MCP.">
  <figcaption>Selected services become one local graph. The coding agent you already use searches, traverses, and fetches that context through MCP.</figcaption>
</figure>

## Context follows attention

AgentGraph builds context in three ways:

- **Observe:** when you keep a supported page focused, the Chrome extension tells the local server which resource mattered and its connector fetches it.
- **Fetch:** an agent or the CLI can request a specific missing or stale resource directly.
- **Refresh:** polling and ingest keep configured or already-known resources current.

Only browser observation updates `observed_at`. Direct fetch and background refresh add useful context without pretending the human looked at it. This distinction powers the local retention model. [See how it works](/how-it-works.html).

## What the agent can perceive today

| Connector | What it contributes |
| --- | --- |
| Gmail | Email threads, participants, subjects, bodies, and attachment references |
| Google Drive, Docs, Sheets | Folders, files, content, ownership, authorship, and containment |
| Slack | Channels and DMs, messages, replies, authors, mentions, and attachments |
| Discord | Channels, DMs, threads, messages, authors, mentions, and attachments |
| RSS | Feeds, posts, dates, authors, and publication relationships |
| Web | Configured pages and bookmarks with titles, text, metadata, and URLs |

These are not the whole product. They prove a connector pattern that teams, individuals, and open-source contributors can extend to internal systems, niche tools, exports, local databases, and APIs.

<div class="connector-promise"><strong>Bring any service into your agent's world.</strong> Use the bundled connectors today, then build the long tail of context your own agent needs.</div>

[Explore connectors](/connectors.html) or [build your own](/extending.html).

## Trace a decision

The reproducible launch demo asks an agent to reconcile a customer requirement in Gmail, an engineering decision in Slack, a stale Drive plan, one article captured by browser observation, and another page fetched directly by the agent.

> Before I reply to Maya, reconstruct the Atlas synchronization decision. What did she require, what did engineering agree, does the Drive plan match, and which research supports the decision? Flag contradictions and link every source.

[Run the fictional Atlas demo](/demo.html).

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
    <p>Search, query, fetch, observe, poll, ingest, and operate the local graph.</p>
  </section>
  <section class="doc-card">
    <h3><a href="/mcp/">MCP tools</a></h3>
    <p>Connect an existing agent to search, traversal, fetch, and graph-management tools.</p>
  </section>
</div>

## Local by design

Indexed content is stored in SQLite on your machine. Source API calls run from your machine under your credentials. The project does not operate a hosted graph service or receive indexed content through a project-controlled backend.

An MCP client you connect can read content from the local graph and is governed by that client's data practices. Read the [Privacy Policy](/privacy.html), [Terms of Service](/terms.html), and [retention model](/retention.html).
