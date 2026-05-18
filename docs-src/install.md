+++
title = "Install"
description = "Install AgentGraph, authenticate connectors, run the server, connect the extension, and expose MCP."
nav_title = "Install"
section = "Start"
order = 20
summary = "Set up AgentGraph once, authenticate the sources you care about, then run it as a local service for your browser and AI clients."
output = "install.html"
source_path = "docs-src/install.md"
+++

The install flow below assumes the default SQLite backend. If you want to run AgentGraph against PostgreSQL instead, follow the normal install steps and then see [PostgreSQL](/postgresql.html).

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
```

## Authenticate connectors

The fastest path is the setup wizard:

```bash
agentgraph onboard
```

You can also authenticate one connector at a time:

```bash
agentgraph auth google
agentgraph auth slack
agentgraph auth discord
```

<div class="callout">
  <p><strong>Credential storage:</strong> credentials live in <code>~/.agentgraph/</code> by default, or under <code>AGENTGRAPH_CONFIG_DIR</code> if you set a custom config directory.</p>
</div>

## Run the server

`agentgraph serve` accepts browser dwell events, runs connector pollers, serves the viewer, and exposes the local HTTP backend.

```bash
agentgraph serve
agentgraph serve --reload
```

Logs are written to `/tmp/agentgraph.log`.

## Install the browser extension

Build the extension:

```bash
cd extension
npm install
npm run build
```

Then load `extension/dist/` from `chrome://extensions` with Developer Mode enabled.

## Connect MCP clients

Print the client config:

```bash
agentgraph mcp-config
```

See [`mcp-config`](/commands/mcp-config.html) for the command details and transport examples.

For ChatGPT, enable Developer mode and point a remote MCP connector at an AgentGraph SSE or streaming HTTP endpoint.

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
  <key>StandardOutPath</key>
  <string>/tmp/agentgraph.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/agentgraph.log</string>
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
StandardOutput=append:/tmp/agentgraph.log
StandardError=append:/tmp/agentgraph.log

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now agentgraph
```
