+++
title = "Install"
description = "Install AgentGraph, run the server, connect the extension, and expose MCP."
nav_title = "Install"
section = "Start"
order = 20
summary = "Set up AgentGraph locally, connect the extension, and hand off to Quickstart for authentication and first indexing."
output = "install.html"
source_path = "docs-src/install.md"
+++

The install flow below uses the default SQLite backend.

## Prerequisites

AgentGraph expects Python 3.12 or later and [uv](https://docs.astral.sh/uv/).

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Sync dependencies

Clone the repository and install the first-party connectors you need.

```bash
git clone https://github.com/simonexmachina/agent-graph
cd agent-graph
uv sync --extra all
```

You can also sync only the connectors you want:

```bash
uv sync --extra google
uv sync --extra slack
uv sync --extra discord
uv sync --extra rss
```

<div class="callout">
  <p><strong>Credential storage:</strong> credentials live in <code>~/.agentgraph/</code> by default, or under <code>AGENTGRAPH_CONFIG_DIR</code> if you set a custom config directory.</p>
</div>

## Run the server

`agentgraph serve` accepts browser dwell events, runs connector pollers, serves the viewer, and exposes the local HTTP backend.

```bash
agentgraph serve
```

Logs are written to standard output.

## Install the browser extension

Install the [AgentGraph Chrome Extension](https://chromewebstore.google.com/detail/agentgraph-extension/iilkfclglabllelhjacijldknapbhidi?authuser=0&hl=en-AU) from the Chrome Web Store.

If you want to build the extension yourself instead, use:

```bash
cd extension
npm install
npm run build
```

Then open `chrome://extensions`, enable Developer Mode, click **Load unpacked**, and select `extension/dist/`.

After the extension is installed, continue with [Quickstart](/quickstart.html) to authenticate connectors, start the server, and verify that your first entities land in the graph.

## Connect MCP clients

Print the client config:

```bash
agentgraph mcp-config
```

See [`mcp-config`](/commands/mcp-config.html) for the command details and transport examples.

For ChatGPT, do not use the stdio JSON config. Run `agentgraph mcp-serve --transport streamable-http --port 8808`, expose `http://127.0.0.1:8808/mcp` through an HTTPS tunnel, then create an app/connector in ChatGPT developer mode with the public URL ending in `/mcp`.

## Run in the background

Only `agentgraph serve` needs to be long-running. MCP stdio mode is spawned on demand by the client.

### macOS launchd

```bash
which agentgraph

cat > ~/Library/LaunchAgents/com.agentgraph.serve.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.agentgraph.serve</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/you/.local/bin/agentgraph</string>
    <string>serve</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>EnvironmentVariables</key>
  <dict>
    <key>AGENTGRAPH_LOG_FILE</key>
    <string>/tmp/agentgraph.log</string>
  </dict>
</dict>
</plist>
EOF

launchctl load ~/Library/LaunchAgents/com.agentgraph.serve.plist
```

### Linux systemd

```bash
which agentgraph

mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/agentgraph.service <<'EOF'
[Unit]
Description=AgentGraph local knowledge graph server
After=network.target

[Service]
ExecStart=/home/you/.local/bin/agentgraph serve
Restart=on-failure
RestartSec=5
StandardOutput=append:/tmp/agentgraph-serve.log
StandardError=append:/tmp/agentgraph-serve.log

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now agentgraph
```
