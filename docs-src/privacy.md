+++
title = "Privacy"
description = "AgentGraph privacy policy."
nav_title = "Privacy"
section = "Reference"
order = 30
summary = "AgentGraph is a local tool. Indexed content, credentials, and query traffic stay on your machine unless another client you choose reads from your local graph."
output = "privacy.html"
source_path = "docs-src/privacy.md"
+++

## What AgentGraph is

AgentGraph is an open-source application that you install and run locally on your own computer. It indexes content from connected sources into a local database and makes that data searchable via a CLI, web viewer, and MCP server. The storage backend is pluggable; SQLite is the default, and PostgreSQL is also supported.

## Data collection and storage

- Indexed content is stored in a local SQLite database by default, or in PostgreSQL if you configure the `postgres` backend.
- Credentials are stored in `credentials.json` inside the AgentGraph config directory.
- AgentGraph does not operate a hosted service and does not send indexed content to a server controlled by the project.

## Browser extension data flow

- The browser extension stores its configured local server URL and a cached copy of supported URL patterns in Chrome local storage.
- When you dwell on a supported page, the extension sends the page URL to your local AgentGraph server so the matching connector can fetch that resource.
- On Gmail, the extension also extracts the currently open Gmail thread identifier from the page so the local AgentGraph server can fetch the correct thread through the Gmail API.
- The extension talks only to `localhost` or `127.0.0.1` for AgentGraph server requests; it does not call a project-operated remote extension backend.

## Google API usage

AgentGraph uses Google APIs to read Google Docs, Google Sheets, Google Drive, and Gmail content on your behalf. AgentGraph's use of information received from Google APIs adheres to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements.

## Third-party API calls

AgentGraph makes outbound API calls directly from your machine to the services you have authenticated with, such as Google, Slack, and Discord. Those calls run under your own credentials and are subject to those services' privacy policies.

If you connect an MCP client, that client can receive content from your local AgentGraph database. That part of the flow is governed by the privacy policy of the client you chose.

## Open source

The project source is public at [github.com/simonexmachina/agent-graph](https://github.com/simonexmachina/agent-graph). There is no hidden telemetry layer in AgentGraph itself.

## Changes

If this policy changes materially, the updated version will be published at this URL with a revised date.
