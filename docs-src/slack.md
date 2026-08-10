+++
title = "Slack authentication"
description = "Create an internal Slack app and authenticate AgentGraph with user OAuth PKCE or the browser-session fallback."
nav_title = "Slack auth"
section = "Configuration"
order = 20
summary = "Slack user OAuth with PKCE is the default. Workspace admins create and approve an internal app; browser-session credentials remain an explicit fallback."
output = "slack.html"
source_path = "docs-src/slack.md"
+++

## Create the internal app

Ask a Slack workspace admin to open `https://api.slack.com/apps`, choose **Create
New App → From a manifest**, select the workspace, and use the packaged manifest at
`packages/agentgraph-connector-slack/agentgraph_connector_slack/slack-app-manifest.yaml`.
The manifest enables PKCE, rotating tokens, and the default callback
`http://localhost:8766/slack/oauth/callback`.

The required user scopes cover public channels, private channels, direct messages,
group direct messages, and profiles: `channels:read`, `channels:history`,
`groups:read`, `groups:history`, `im:read`, `im:history`, `mpim:read`,
`mpim:history`, and `users:read`. `users:read.email` is optional. A user may decline
email access and continue with profile enrichment that omits email.

The admin must approve the app and its requested scopes under the workspace's app
management policy. Copy the app's Client ID after creation; no client secret is used
by the localhost PKCE flow.

## Configure and authorize

AgentGraph prompts for the Client ID on first authorization and stores it with that
account's rotating credentials. To skip the prompt, set it in the environment or
AgentGraph config `.env`:

```bash
AGENTGRAPH_SLACK_CLIENT_ID=1234567890.1234567890
```

If the admin registered a different localhost callback, set its exact value. Slack
requires the authorization request and registered redirect to match exactly.

```bash
AGENTGRAPH_SLACK_REDIRECT_URI=http://localhost:9000/slack/oauth/callback
```

Run auth and choose official Slack user OAuth (OIDC/PKCE). AgentGraph prints the app
setup requirements before opening Slack, validates the returned state, exchanges the
code with PKCE, and waits at most five minutes for the callback. Use
`--method oauth` to bypass the chooser.

```bash
agentgraph auth slack
agentgraph auth status --verify --json
```

OAuth access tokens refresh five minutes before expiry. Slack's rotated access and
refresh tokens are written atomically. Re-authentication and refresh reuse the Client
ID stored per account, so the environment variable is not required again.

Use `--add` for another identity. Re-authenticating an existing
`slack:<team>:<user>` replaces that identity's method; separate identities may mix
OAuth and browser credentials.

## Revoke access

Remove local credentials for one identity or the provider:

```bash
agentgraph auth remove slack --account slack:T012345:U012345
agentgraph auth remove slack
```

Local removal does not revoke the Slack grant. The user can revoke it from Slack's
connected-app settings, or an admin can remove the internal app from the workspace.

## Browser-session fallback

Browser credentials are less durable and should only be used when the internal app
cannot be approved. Select the fallback explicitly and provide the `xoxc` token and
`d` cookie from a logged-in Slack browser session:

```bash
agentgraph auth slack --method browser --xoxc-token "$XOXC" --d-cookie "$D_COOKIE"
```

For compatibility, supplying either credential option without `--method` infers
browser mode. Explicit OAuth rejects browser credential flags. Existing records that
predate `auth_method` continue to load as browser credentials without migration.
