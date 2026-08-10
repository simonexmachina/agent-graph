+++
title = "Slack authentication"
description = "Create an internal Slack app and authenticate AgentGraph with user OAuth PKCE or the browser-session fallback."
nav_title = "Slack auth"
section = "Configuration"
order = 20
summary = "Slack user OAuth with PKCE is the default. The guided flow helps admins create an internal app and helps members request one; browser-session credentials remain an explicit fallback."
output = "slack.html"
source_path = "docs-src/slack.md"
+++

## Start the guided flow

Run auth and choose Slack user OAuth with PKCE. AgentGraph reuses a Client ID stored
with the selected account or reads `AGENTGRAPH_SLACK_CLIENT_ID`. On first setup it
asks whether you have admin permission in the workspace you want to connect.

```bash
agentgraph auth slack
```

An admin follows the printed steps to open `https://api.slack.com/apps`, choose
**Create New App → From an app manifest**, select the target workspace, paste the
printed manifest, approve the app, and enter its Client ID.

A non-admin chooses either **Enter a Client ID provided by a Slack admin** or **Set
up or request the AgentGraph app**. The second option asks whether the target
workspace appears in Slack's **Pick a workspace** list. When it appears, the member
can create AgentGraph from the printed manifest and enter its Client ID. When it does
not, AgentGraph prints a copyable request for a Workspace Owner or app manager along
with the project website and complete manifest. Rerun the command and choose the
first non-admin option after the admin supplies the Client ID.

The packaged manifest enables PKCE and rotating tokens and contains the only
supported callback, `http://localhost:8766/slack/oauth/callback`.

A newly created, undistributed Slack app belongs to the workspace selected during
creation and cannot be authorized into a different workspace. Creating AgentGraph in
a personal or test workspace will therefore make only that workspace eligible in the
OAuth chooser. The target workspace must have its own app and Client ID. Enabling
cross-workspace app distribution is a separate deployment model and is outside this
internal-app setup.

The required user scopes cover public channels, private channels, direct messages,
group direct messages, and profiles: `channels:read`, `channels:history`,
`groups:read`, `groups:history`, `im:read`, `im:history`, `mpim:read`,
`mpim:history`, and `users:read`. `users:read.email` is optional. A user may decline
email access and continue with profile enrichment that omits email.

Slack's manifest validator requires the base `users:read` scope to also appear in
`user_optional` when the `users:read.email` extension is optional. AgentGraph still
treats `users:read` as operationally required and validates that it was granted;
only email enrichment may be declined.

The app must be approved under the workspace's app management policy. No client
secret is used by the localhost PKCE flow. During authorization:

- **Allow** completes authorization immediately.
- **Request approval** submits the app to a Workspace Owner or app manager. Rerun
  auth with the same Client ID after Slackbot confirms approval.
- A blocked installation without a request action requires help from a Workspace
  Owner or app manager.

Slack cannot offer an app approval request until the app exists in the target
workspace. If the target workspace does not appear during app creation, ensure the
browser is signed in to it; if it remains absent, use AgentGraph's printed admin
request.

## Configure and authorize

AgentGraph accepts the Client ID in the guided admin and non-admin flows and stores it
with that account's rotating credentials. To supply it ahead of time, set it in the
environment or AgentGraph config `.env`:

```bash
AGENTGRAPH_SLACK_CLIENT_ID=1234567890.1234567890
```

AgentGraph opens Slack, validates the returned state, exchanges the code with PKCE,
and waits at most five minutes for the callback. If an approval request is pending,
the timeout tells the user to rerun after Slackbot confirms it. Use `--method oauth`
to bypass only the method chooser; setup questions still appear when no Client ID is
stored or configured.

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
