+++
title = "How AgentGraph works"
description = "How observation, fetch, refresh and retention fit together."
nav_title = "How it works"
section = "Start"
order = 40
summary = "Context enters AgentGraph through browser observation, agent-initiated fetches, and refresh. Every path uses connector packages to produce one local graph."
output = "how-it-works.html"
source_path = "docs-src/how-it-works.md"
+++

AgentGraph is infrastructure for the agent you already use. It provides a CLI and an MCP server so your agents have a searchable, traversable representation of your digital world – messages, documents, people, feeds, and web pages.

<figure class="architecture-figure architecture-figure-fit" tabindex="0">
  <img src="/assets/diagrams/architecture-overview-dark.svg" alt="Observe, Fetch, and Refresh converge on connector packages that read selected services and write to a local graph. Agents access the graph through the CLI or MCP, while Expiry applies the retention model.">
  <figcaption>Observe, Fetch, and Refresh converge on connector packages and the local graph. Expiry applies the retention model to stored content.</figcaption>
</figure>

## Three ways context enters

### Observe

The Chrome extension downloads the current set of connector-owned URL patterns from the local AgentGraph server. When your browser remains focused for 3 seconds on a page that has an installed connector, the extension sends the URL to the local server.

The owning connector then fetches the resource through its source API and inserts entities, people, and edges into the graph.

This is targeted capture, not a copy of arbitrary browsing. Unknown URLs are ignored. The extension talks to `localhost` or `127.0.0.1` and does not send any page content to the AgentGraph backend.

### Fetch

An agent can request a resource directly with `agentgraph fetch <platform> <resource-id>` or refresh an existing graph entity with `agentgraph fetch-entity <entity-id>`.

### Refresh

Connectors poll source APIs for changes to keep the entity updated in the graph when the resource changes. Some connectors, such as Gmail, also provide an `ingest` command to perform a broader historical ingestion.

## The graph model

Connectors add the following items to the graph:

- **Entities:** channels, messages, email threads, documents, spreadsheets, folders, and web or feed documents.
- **People:** source identities, unified automatically when connectors provide the same canonical email and mergeable manually with confirmation otherwise.
- **Edges:** relationships such as `authored`, `participated_in`, `posted_in`, `replied_to`, `mentions`, `contains`, and `references`.

Content is available through full-text and semantic search. Edges make it possible to move from a person to their conversations and documents, from a message to its thread or channel, and from a folder or source document to related context.

## Attention and retention

Observation provides an explicit signal about which resources mattered to the user. Observable entities expire after `AGENTGRAPH_RETENTION_DAYS`, which defaults to 90 days, measured from their latest observation or their local insertion time if never observed. Messages are retained until their parent channel or email thread expires, while people remain only while connected to the graph.

Entities can be bookmarked to protect them from automatic expiration.

See [Entity retention](/retention.html) for the complete retention policy.

## Where the data goes

The graph stores content, metadata, embeddings, edges, observations, and connector cursors in a local SQLite database. Calls to source APIs run from your machine using credentials stored in the AgentGraph config directory.
