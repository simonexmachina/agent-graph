+++
title = "Install"
description = "Install AgentGraph with uv, configure optional connectors, background services, and MCP transports."
nav_title = "Install"
section = "Start"
order = 20
summary = "Install the local application, connect the sources you need, and configure optional MCP clients."
output = "install.html"
source_path = "docs-src/install.md"
+++

The install flow below uses the default SQLite backend.

## Prerequisites

AgentGraph expects Python 3.12 or later and [uv](https://docs.astral.sh/uv/).

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Install AgentGraph

Install AgentGraph with every first-party connector:

```bash
uv tool install 'agentgraph-server[all]'
```

This makes the `agentgraph` command available in your shell.

Or install only the connector support you need:

```bash
uv tool install 'agentgraph-server'
uv tool install 'agentgraph-server[google]'
uv tool install 'agentgraph-server[slack]'
uv tool install 'agentgraph-server[discord]'
uv tool install 'agentgraph-server[rss]'
uv tool install 'agentgraph-server[web]'
```

## Start the server

To start the server in a terminal session, or see below for instructions on how to keep the server running in the background.

```bash
agentgraph server
```

## Connect sources

Run guided onboarding to set up each installed connector that provides an interactive flow:

```bash
agentgraph onboard
```

## Install the AgentGraph skill

The following command will install an AgentGraph skill in `~/.agents/skills` and `~/.claude/skills`:

```bash
agentgraph install-skill
```

## Install the browser extension

Install the [AgentGraph Chrome Extension](https://chromewebstore.google.com/detail/agentgraph-extension/iilkfclglabllelhjacijldknapbhidi?authuser=0&hl=en-AU) from the Chrome Web Store.

After the extension is installed, start `agentgraph serve`, then open a supported resource and keep it focused past the default three-second observation threshold.

## Optional: Connect ChatGPT or Claude

If you want to use AgentGraph from ChatGPT or Claude instead of through your coding agent, connect it as an MCP client.

For ChatGPT's Codex client, register the local stdio server from your terminal:

```bash
codex mcp add agentgraph -- "$(which agentgraph)" mcp-serve
```

For Claude Code, use the equivalent command:

```bash
claude mcp add agentgraph -- "$(which agentgraph)" mcp-serve
```

## Run in the background

`agentgraph serve` needs to be long-running to provide ongoing polling and to support the viewer.

### macOS launchd

```bash
cat > ~/Library/LaunchAgents/com.agentgraph.serve.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.agentgraph.serve</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(which agentgraph)</string>
    <string>serve</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
</dict>
</plist>
EOF

launchctl load ~/Library/LaunchAgents/com.agentgraph.serve.plist
```

### Linux systemd

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/agentgraph.service <<EOF
[Unit]
Description=AgentGraph local knowledge graph server
After=network.target

[Service]
ExecStart=$(which agentgraph) serve
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
