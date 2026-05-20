+++
title = "Tester Extension Install"
description = "Install a prebuilt AgentGraph extension bundle from GitHub artifacts or releases."
nav_title = "Tester Extension Install"
nav_hidden = true
section = "Start"
order = 40
summary = "Use this flow if you want to test the extension without building it locally."
output = "tester-extension-install.html"
source_path = "docs-src/tester-extension-install.md"
+++

This page is for testers and developers who want a prebuilt extension bundle. It is not the long-term one-click install path for normal users. Until the Chrome Web Store listing is live, use GitHub release assets or workflow artifacts.

## 1. Start AgentGraph locally

The extension still talks to a local AgentGraph server running on your machine.

```bash
agentgraph serve
```

The default server URL is `http://127.0.0.1:8765`. The extension defaults to `http://localhost:8765`, which reaches the same local service in the normal setup.

## 2. Download a prebuilt extension bundle

Choose one of these sources:

- The published release asset [`agentgraph-extension.zip`](https://github.com/simonexmachina/agent-graph/releases/download/v0.1.0/agentgraph-extension.zip)
- A pull request or branch workflow artifact named `agentgraph-extension`

If you are downloading a workflow artifact, GitHub may wrap the extension zip inside an outer artifact download. Extract the downloaded archive until you have `agentgraph-extension.zip`.

## 3. Unzip the bundle locally

After extraction, you should have a directory named `agentgraph-extension/` containing files such as `manifest.json`, `background.js`, `popup.html`, and `assets/icon-128.png`.

## 4. Load the unpacked extension in Chrome

1. Open `chrome://extensions`
2. Enable Developer Mode
3. Click **Load unpacked**
4. Select the unzipped `agentgraph-extension/` directory

## 5. Configure the server URL if needed

If your AgentGraph server is not running on the default port, open the extension details page and use **Extension options**, or open the popup and click **Server settings**.

The first supported values are:

- `http://localhost:<port>`
- `http://127.0.0.1:<port>`

## 6. Verify the extension is talking to the server

- Open the popup and confirm the configured server URL is correct.
- Check that the popup shows the server as online.
- Visit a supported Slack, Discord, Google Docs, Drive, Sheets, or Gmail URL and leave it focused long enough for the dwell timer to trigger.

## Notes

- This tester flow is intended for manual QA, dogfooding, and trying unreleased changes.
- For source builds from this repo, follow the normal [Install](/install.html) or [Quickstart](/quickstart.html) flow instead.
