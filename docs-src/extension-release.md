+++
title = "Extension Distribution"
description = "Chrome extension release, tester distribution, and Chrome Web Store submission notes."
nav_title = "Extension Distribution"
section = "Reference"
order = 40
summary = "Use this checklist for CI artifacts, tester installs, and Chrome Web Store submission prep."
output = "extension-distribution.html"
source_path = "docs-src/extension-release.md"
+++

This page tracks the release and review requirements for the AgentGraph Chrome extension. The extension is still local-first: it talks to a user-run AgentGraph server on `localhost` or `127.0.0.1`, and it does not depend on a hosted AgentGraph service.

## Release checklist

- Build the extension with `npm --prefix extension ci` and `npm --prefix extension run build`.
- Confirm the packaged artifact contains a loadable unpacked directory rooted at `agentgraph-extension/`.
- Verify the options page can switch between `http://localhost:<port>` and `http://127.0.0.1:<port>`.
- Verify the popup reports the configured server URL and server health.
- Confirm the extension still observes supported URLs and triggers `POST /fetch-url`.
- Capture fresh Chrome Web Store screenshots from the built extension before submission.

## Bundled assets

- Manifest icons: `extension/assets/icon-16.png`, `icon-32.png`, `icon-48.png`, `icon-128.png`
- Source artwork: `extension/assets/icon.svg`
- CI artifact: `agentgraph-extension.zip`

## Chrome Web Store listing draft

**Short description**

Index the Slack, Discord, Google Docs, Drive, Sheets, and Gmail pages you actually visit into your local AgentGraph server.

**Description**

AgentGraph Extension watches supported browser tabs and tells your local AgentGraph server when you have spent enough time on a page for it to matter. That lets AgentGraph fetch the page you are actively using instead of bulk-syncing everything up front.

The extension is designed for a local-first workflow:

- It talks only to a locally running AgentGraph server that you control.
- It stores the configured local server URL in Chrome storage.
- It reads Gmail page context only to identify the open thread so the local AgentGraph server can fetch the correct Gmail conversation.
- Indexed content stays in your local AgentGraph database unless another client you explicitly connect reads from it.

## Permissions rationale

- `tabs`: detect the active tab URL and know when focus changes so the dwell timer applies only to the page the user is actively reading.
- `storage`: persist the configured local server URL and cached connector URL patterns across extension restarts.
- `https://mail.google.com/*`: run the Gmail content script that identifies the currently open Gmail thread.
- `http://localhost/*` and `http://127.0.0.1/*`: call the user-run AgentGraph server for health checks, connector metadata, and fetch requests.

## Reviewer notes

AgentGraph Extension does not proxy traffic through a vendor-controlled backend. The extension sends requests only to the user's local AgentGraph server, which defaults to `http://localhost:8765` and can also be configured to `http://127.0.0.1:<port>`.

The Gmail content script does not scrape the whole mailbox in the browser. It extracts the currently open Gmail message or thread identifier so the local server can fetch the correct Gmail thread via the user's own Google API credentials.

The `tabs` permission is required so the extension can start and stop dwell timers when the active tab changes, and so it can show current observation state in the popup.

## Privacy disclosure copy

AgentGraph Extension stores a local server URL and a cached list of supported URL patterns in Chrome local storage. It sends visited supported URLs, and Gmail thread identifiers when applicable, to a local AgentGraph server running on the same machine. It does not send browsing activity to an AgentGraph-operated remote service.

## Support

- Source: [github.com/simonexmachina/agent-graph](https://github.com/simonexmachina/agent-graph)
- Issues: [github.com/simonexmachina/agent-graph/issues](https://github.com/simonexmachina/agent-graph/issues)
