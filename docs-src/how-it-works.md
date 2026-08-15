+++
title = "How AgentGraph works"
description = "How observation, direct fetch, connector refresh, the local graph, and MCP fit together."
nav_title = "How it works"
section = "Start"
order = 40
summary = "Context enters AgentGraph through browser observation, agent-initiated fetches, and connector refresh. Every path uses connector packages to produce one local graph."
output = "how-it-works.html"
source_path = "docs-src/how-it-works.md"
+++

AgentGraph is infrastructure for the agent you already use. It does not answer questions itself. It gives an MCP client or CLI a searchable, traversable representation of selected messages, documents, people, feeds, and web pages.

<figure class="architecture-figure">
  <img src="/assets/diagrams/architecture-overview-dark.svg" alt="Selected online services connect to AgentGraph on the user's machine. Browser observation, agent fetches, and background refresh converge on connector packages and a local graph exposed through MCP.">
  <figcaption>Connectors translate source-specific resources into a shared local model. MCP lets an existing agent search, traverse, and fetch that context.</figcaption>
</figure>

## Three ways context enters

### Observe

The Chrome extension downloads the current set of connector-owned URL patterns from the local AgentGraph server. When a supported tab remains focused for the configured observation threshold, the extension sends the URL and a unique observation ID to the local server. Gmail observations also include the thread identifier needed to resolve the page reliably.

The owning connector then fetches the resource through its source API and returns entities, people, and edges. Only after that resource is persisted does AgentGraph record the observation and update `observed_at`.

This is targeted capture, not a copy of arbitrary browsing. Unknown URLs are ignored. The extension talks to `localhost` or `127.0.0.1` and does not send page content to an AgentGraph-operated backend.

### Fetch

An agent can request a resource directly through `fetch_entity_tool(platform, resource_id)` or refresh an existing graph entity with `fetch_entity_by_id_tool(entity_id)`. The CLI exposes the equivalent `fetch` and `fetch-entity` commands.

Direct fetch uses the same owning connector and persists the same graph-shaped batch as observation. It does not set `observed_at`, because fetching a resource on demand is not evidence that the human looked at it.

### Refresh

Connectors can poll source APIs for changes and can optionally expose a broader historical ingest. Polling keeps already-known resources current; ingest loads a configured corpus. Neither path changes `observed_at`.

<figure class="architecture-figure">
  <img src="/assets/diagrams/context-lifecycle-dark.svg" alt="Sequence diagram contrasting browser observation, direct agent fetch, and background connector refresh. Only observation updates observed_at.">
  <figcaption>Observation, direct fetch, and refresh share connector fetch logic but carry different attention and retention semantics.</figcaption>
</figure>

## The graph model

Connectors return a common `EntityBatch` containing:

- **Entities:** channels, messages, email threads, documents, spreadsheets, folders, and web or feed documents.
- **People:** source identities, unified automatically when connectors provide the same canonical email and mergeable manually with confirmation otherwise.
- **Edges:** relationships such as `authored`, `participated_in`, `posted_in`, `replied_to`, `mentions`, `contains`, and `references`.

Content is available through full-text and semantic search. Edges make it possible to move from a person to their conversations and documents, from a message to its thread or channel, and from a folder or source document to related context.

## Attention and retention

Observation provides an explicit signal about which resources mattered to the user. Observable entities expire after `AGENTGRAPH_RETENTION_DAYS`, which defaults to 90 days, measured from their latest observation or their local insertion time if never observed. Messages follow their parent channel or email thread, while people remain only while connected to the graph. Bookmarks protect selected entities from automatic expiration.

See [Entity retention](/retention.html) for the complete Observed, Owned, and Connected policy tables.

## Where the data goes

The built-in backend stores content, metadata, embeddings, edges, observations, and connector cursors in a local SQLite database. Source API calls run from your machine under credentials stored in the AgentGraph config directory.

An MCP client can receive content it reads from this graph. That client and its model provider have their own data-handling policies. See [Privacy](/privacy.html).
