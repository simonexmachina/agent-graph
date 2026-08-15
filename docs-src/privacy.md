+++
title = "Privacy Policy"
description = "How AgentGraph accesses, stores, retains, deletes, and shares connected-service data."
nav_title = "Privacy"
nav_hidden = true
section = "Reference"
order = 30
summary = "AgentGraph stores indexed content and credentials locally. Source APIs and MCP clients you choose remain separate data-handling boundaries."
output = "privacy.html"
source_path = "docs-src/privacy.md"
+++

Effective date: August 15, 2026.

## What AgentGraph is

AgentGraph is an open-source application that you install and run locally on your own computer. It indexes content from connected sources into a local SQLite database and makes that data searchable via a CLI, web viewer, and MCP server.

## Data collection and storage

- Indexed content is stored in a local SQLite database.
- Provider tokens are stored in `credentials.json` inside the AgentGraph config directory.
- Google uses Desktop OAuth client credentials packaged with AgentGraph. The client ID is
  recorded with each account for token refresh; the packaged client secret is used only
  in memory and is not copied into the user's `credentials.json`.
- AgentGraph does not operate a hosted service and does not send indexed content to a server controlled by the project.

AgentGraph uses indexed content only to provide the local search, graph navigation, source retrieval, and connector behavior requested by the user. The project does not use connected-service data for advertising or to train or improve generalized AI or machine-learning models.

## Browser extension data flow

- The browser extension stores its configured local server URL and a cached copy of supported URL patterns in Chrome local storage, and refreshes that metadata periodically from the local server.
- When you observe a supported page, the extension sends the page URL to your local AgentGraph server so the matching connector can fetch that resource.
- RSS article patterns are derived from previously indexed feed entry links. A matching RSS prefix never by itself attributes a page: the local server accepts an RSS observation only for an exact known entry URL.
- On Gmail, the extension also extracts the currently open Gmail thread identifier from the page so the local AgentGraph server can fetch the correct thread through the Gmail API.
- The extension talks only to `localhost` or `127.0.0.1` for AgentGraph server requests; it does not call a project-operated remote extension backend.

## Google API usage

AgentGraph uses Google APIs to read Google Docs, Google Sheets, Google Drive, and Gmail content on your behalf. AgentGraph's use of information received from Google APIs adheres to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements.

## Third-party API calls

AgentGraph makes outbound API calls directly from your machine to the services you have authenticated with, such as Google, Slack, and Discord. Those calls run under your own credentials and are subject to those services' privacy policies.

If you connect an MCP client, that client can receive content from your local AgentGraph database. That part of the flow is governed by the privacy policy of the client you chose.

## Retention and deletion

Observable entities use a configurable retention window, `AGENTGRAPH_RETENTION_DAYS`, which defaults to 90 days. Browser observation updates an entity's `observed_at` timestamp. Direct fetch, polling, ingest, and source changes do not. Messages and attachments can follow a parent entity's lifecycle, while Person entities remain only while connected to other graph entities. Bookmarks protect selected entities from automatic expiration.

You can delete an entity with `agentgraph delete`, remove bookmark protection with `agentgraph bookmark --remove`, or remove the local database and config directory to delete the entire local graph. Deleting local AgentGraph data does not delete the source material from Gmail, Drive, Slack, Discord, or another connected service.

See [Entity retention](/retention.html) for the complete policy and expiration behavior.

## Revoking access

- Run `agentgraph auth remove <provider>` or use the corresponding MCP authentication-removal tool to remove locally stored provider credentials.
- Revoke AgentGraph in the connected provider's account or application settings to invalidate access at the source.
- Remove configured RSS feeds or Web observation URLs with their connector `remove` commands.
- Stop `agentgraph serve` and remove the Chrome extension to stop browser observation.
- Remove AgentGraph from the MCP client to stop that client reading the local graph.

Removing credentials stops future authenticated API access but does not automatically delete content already indexed locally. Delete the relevant entities or local database separately when required.

## Open source

The project source is public at [github.com/simonexmachina/agent-graph](https://github.com/simonexmachina/agent-graph). There is no hidden telemetry layer in AgentGraph itself.

## Changes

If this policy changes materially, the updated version will be published at this URL with a revised date.

## Contact

Privacy questions can be sent to [simon.wade@gmail.com](mailto:simon.wade@gmail.com). Non-sensitive defects and documentation issues can be reported at [github.com/simonexmachina/agent-graph/issues](https://github.com/simonexmachina/agent-graph/issues).

See also the [Terms of Service](/terms.html).
