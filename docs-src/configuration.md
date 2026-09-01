+++
title = "Configuration"
description = "Configuration directory, database settings, observation threshold, retention, and server settings."
nav_title = "Configuration"
section = "Configuration"
order = 10
summary = "AgentGraph reads settings from environment variables and from `.env` files in the config directory and the local directory."
output = "configuration.html"
source_path = "docs-src/configuration.md"
+++

## Config directory

The config directory defaults to `~/.agentgraph`. Change it with `AGENTGRAPH_CONFIG_DIR`.

```bash
AGENTGRAPH_CONFIG_DIR=/path/to/agentgraph agentgraph serve
```

That directory controls:

- `config.toml`
- `config.yaml` (optional alternative for connector configuration)
- `credentials.json`
- the config `.env`
- the default SQLite database path

Connector configuration that is not a secret, such as RSS feed URLs, is stored in
`config.toml` by default, or `config.yaml` if that file exists. Provider tokens and
account identifiers remain in `credentials.json`. Google records include the public
OAuth client ID that issued each refresh token, but never the packaged OAuth client
secret. Desktop OAuth client credentials distributed with AgentGraph are public
application identifiers, not a security boundary.

## Storage backend

AgentGraph stores the graph in SQLite by default, and the install and quickstart docs assume this setup.

## Core settings

### `AGENTGRAPH_CONFIG_DIR`

Default: `~/.agentgraph`

Directory for AgentGraph config, credentials, and the default SQLite database.

### `AGENTGRAPH_BACKEND`

Default: `sqlite`

Persistence backend. The built-in backend is `sqlite`.

### `AGENTGRAPH_BACKEND_SQLITE_PATH`

Default: `$AGENTGRAPH_CONFIG_DIR/agentgraph.db`

SQLite database path.

### `AGENTGRAPH_SERVER_HOST`

Default: `127.0.0.1`

Server bind address.

### `AGENTGRAPH_SERVER_PORT`

Default: `8765`

Server port.

### `AGENTGRAPH_LOG_FILE`

Default: `$AGENTGRAPH_CONFIG_DIR/agentgraph.log`

Path for the rotating server log. The default is stored in the per-user config
directory rather than `/tmp`, so separate user accounts do not share a log file.

### `AGENTGRAPH_OBSERVATION_THRESHOLD_SECONDS`

Default: `3`

Seconds of focus before a fetch is triggered.

For this release, `AGENTGRAPH_DWELL_THRESHOLD_SECONDS` remains accepted as a
deprecated alias. The deprecated `POST /report-dwell` endpoint likewise remains
available for installed extensions; new integrations must use observation names.

### `AGENTGRAPH_POLL_INTERVAL_SECONDS`

Default: unset (each connector uses its own interval)

Override the background polling interval for all connectors. Set it to a positive
number of seconds to use one shared interval, or set it to `0` to disable scheduled
polling. Manual polls triggered with `agentgraph poll` are still available.

### `AGENTGRAPH_RETENTION_DAYS`

Default: `90`

Retention window for directly observable entities. Never-observed entities use their local
insertion time; Messages follow their parent and Persons follow graph connectivity. See
[Entity retention](retention.html).

### `AGENTGRAPH_EMBEDDING_MODEL`

Default: `BAAI/bge-small-en-v1.5`

FastEmbed model used for embeddings.

### `AGENTGRAPH_EMBEDDING_CACHE_DIR`

Default: `$AGENTGRAPH_CONFIG_DIR/models`

Directory holding the downloaded FastEmbed ONNX model (~64 MB). The default lives
in the per-user config directory rather than FastEmbed's own `$TMPDIR` default:
`$TMPDIR` varies between callers and is periodically purged by the OS, which would
make the model re-download from HuggingFace — and make `agentgraph search` fail
outright when the network is unavailable or restricted.

### `AGENTGRAPH_SLACK_CLIENT_ID`

Optional prompt override for Slack OAuth. Use the Client ID of the admin-created
internal Slack app. AgentGraph stores it per authenticated account.

### `AGENTGRAPH_SLACK_OAUTH_CALLBACK_PORT`

Default: `8766`

Port for the temporary local Slack OAuth callback listener. Set this when another
process already uses `8766`; the callback URL remains on `localhost` at
`/slack/oauth/callback`. A custom port must also be registered in the Slack app's
redirect URLs. AgentGraph prints a manifest with the configured callback URL during
Slack app setup.

## Slack workspace filter

If you only want Slack data from one workspace, set `AGENTGRAPH_SLACK_WORKSPACE_ID`.

```bash
AGENTGRAPH_SLACK_WORKSPACE_ID=T04T4TH8W agentgraph serve
```
