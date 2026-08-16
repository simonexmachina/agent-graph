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
uv tool install 'agentgraph-server[google]'
uv tool install 'agentgraph-server[slack]'
uv tool install 'agentgraph-server[discord]'
uv tool install 'agentgraph-server[rss]'
uv tool install 'agentgraph-server[web]'
```

<div class="callout">
  <p><strong>Credential storage:</strong> credentials live in <code>~/.agentgraph/</code> by default, or under <code>AGENTGRAPH_CONFIG_DIR</code> if you set a custom config directory.</p>
</div>

## Connect a source

Run guided onboarding to authenticate each installed connector that requires credentials:

```bash
agentgraph onboard
```

RSS and generic Web connectors do not require provider credentials. See [Connectors](/connectors.html) for their setup and supported sources.

## Install the browser extension

Install the [AgentGraph Chrome Extension](https://chromewebstore.google.com/detail/agentgraph-extension/iilkfclglabllelhjacijldknapbhidi?authuser=0&hl=en-AU) from the Chrome Web Store.

To build the extension yourself, first clone the repository, then run:

```bash
git clone https://github.com/simonexmachina/agent-graph
cd agent-graph/extension
npm install
npm run build
```

Then open `chrome://extensions`, enable Developer Mode, click **Load unpacked**, and select `extension/dist/`.

After the extension is installed, start `agentgraph serve`, then open a supported resource and keep it focused past the default three-second observation threshold.

## Optional: Connect ChatGPT or Claude

If you want to use AgentGraph from ChatGPT or Claude instead of through your coding agent, connect it as an MCP client. For Claude, print the stdio client configuration:

```bash
agentgraph mcp-config
```

Add the printed configuration to Claude Desktop or another compatible MCP client. See [`mcp-config`](/commands/mcp-config.html) for command details and transport examples.

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
