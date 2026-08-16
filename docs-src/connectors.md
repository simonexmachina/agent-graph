+++
title = "Connectors"
description = "What AgentGraph's bundled connectors let an agent perceive and how to build connectors for other services."
nav_title = "Connectors"
section = "Start"
order = 50
summary = "Connectors translate source-specific resources into AgentGraph entities, people, edges, observations, and searchable content."
output = "connectors.html"
source_path = "docs-src/connectors.md"
+++

AgentGraph's bundled connectors are useful integrations today and examples of an open connector pattern. Each connector owns its URLs, authentication, fetch logic, refresh behavior, and source metadata while returning the same graph-shaped output to core AgentGraph.

## Works today

| Connector | What it lets the agent perceive | Context paths |
| --- | --- | --- |
| Gmail | Email threads, participants, subjects, bodies, and attachment references | Observe, fetch, poll, ingest |
| Google Drive | Folders and files, content, ownership, and containment | Observe, fetch, poll |
| Google Docs | Document content, ownership, authorship, and source dates | Observe, fetch, Drive refresh |
| Google Sheets | Sheet values, ownership, authorship, and source dates | Observe, fetch, Drive refresh |
| Slack | Channels and DMs, messages, replies, authors, mentions, and attachments | Observe, fetch, poll |
| Discord | Channels, DMs, threads, messages, authors, mentions, and attachments | Observe, fetch, poll |
| RSS | Feeds, posts, dates, authors, and publication relationships | Observe, fetch, poll |
| Web | Configured pages and bookmarks with titles, text, metadata, and URLs | Observe, fetch |

Connector coverage is intentionally precise. For example, Drive currently records owners rather than every collaborator, and Discord bots cannot access user email addresses. Slack-to-Google person unification works automatically only when both connectors provide the same email; other identities require user-confirmed merging.

## Extensible by design

A connector is a Python package that translates a service into local entities, people, edges, observations, and searchable content. A service does not need to look like Gmail or Slack. Connectors can be built around:

- an API, export, or webhook;
- a local database or structured file;
- a browser-accessible resource;
- an internal system used by one team; or
- a niche public service maintained by its own community.

The required contract is small: declare a stable source name, own and resolve resource identifiers, implement targeted `fetch()`, and register the package. Polling, ingest, authentication, downloads, and identity hooks are optional extensions.

<div class="connector-promise"><strong>Bring any service into your agent's world.</strong> Build a private connector for internal context, publish an integration for a tool you use, or contribute to the long tail of services that agents should be able to navigate.</div>

See [Extending AgentGraph](/extending.html) for the complete interface, example connector, packaging, and registration instructions.

## Community direction

The bundled connectors prove the architecture; they are not presented as a complete integration ecosystem. The long-term direction is a community-maintained library spanning developer tools, issue trackers, notes, calendars, research libraries, media, CRMs, support systems, and the unusual services that matter to individual users.

Until that ecosystem exists, launch copy should distinguish clearly between bundled support, connectors that users can build today, and future community coverage.
