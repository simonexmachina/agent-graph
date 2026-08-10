---
name: slack-auth
description: Authenticate AgentGraph to Slack with user OAuth PKCE by default, or explicitly use browser-session credentials as a fallback.
---

# /slack-auth - Slack Authentication

Use Slack user OAuth with PKCE unless the user explicitly requests the browser-session fallback.

## OAuth (default)

1. Check status without exposing credentials:

```bash
agentgraph auth status --json | jq '.[] | select(.provider == "slack")'
```

2. Start the interactive chooser and select Slack user OAuth with PKCE:

```bash
agentgraph auth slack
```

AgentGraph reuses a Client ID stored with the selected account or reads
`AGENTGRAPH_SLACK_CLIENT_ID`. Otherwise it asks whether the user has admin
permission in the target workspace.

Admins create AgentGraph at `https://api.slack.com/apps` with **Create New App →
From an app manifest**, select the target workspace, paste the manifest printed by
AgentGraph into Slack's **JSON** tab, approve it, and enter its Client ID. The
manifest includes the only
supported callback, `http://localhost:8766/slack/oauth/callback`.

Non-admins choose either **Enter a Client ID provided by a Slack admin** or **Set up
or request the AgentGraph app**. The setup path checks whether the target workspace
appears under **Pick a workspace**. If it does, create the app from the printed
manifest and enter its Client ID. If it does not, send the printed example request
and manifest to a Workspace Owner or app manager, then rerun and enter the supplied
Client ID.

During authorization, click **Allow** when available. If Slack shows **Request
approval**, submit it and rerun with the same Client ID after Slackbot confirms
approval. If installation is blocked without a request action, contact a Workspace
Owner or app manager.

For explicit OAuth selection, use `agentgraph auth slack --method oauth`.

Use `--add` for another identity or `--account slack:<team>:<user>` to replace that identity's current method. Verify `auth_method` afterward:

```bash
agentgraph auth status --verify --json | jq '.[] | select(.provider == "slack") | .accounts'
```

If the user declines optional `users:read.email`, authentication still succeeds without email enrichment.

## Browser fallback

Only use this flow when OAuth cannot be approved or the user explicitly selects it. Load the `agent-browser` skill, connect to a logged-in `app.slack.com` session, and derive the team-specific token:

```bash
TEAM_ID=$(agent-browser get url | sed -n 's#.*app\.slack\.com/client/\(T[A-Z0-9]*\).*#\1#p')
TOKEN=$(agent-browser eval "(() => { const cfg = JSON.parse(localStorage.getItem('localConfig_v2')); return cfg.teams['$TEAM_ID'].token; })()" | jq -r .)
COOKIE=$(agent-browser --json cookies get | jq -r '.data.cookies[] | select(.name == "d" and (.domain | contains("slack"))) | .value' | head -n 1)
```

Validate without printing either secret, then save them through the explicit method:

```bash
if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then echo "missing token" >&2; exit 1; fi
if [ -z "$COOKIE" ] || [ "$COOKIE" = "null" ]; then echo "missing d cookie" >&2; exit 1; fi
case "$TOKEN" in xoxc-*) ;; *) echo "token did not use xoxc prefix" >&2; exit 1;; esac
agentgraph auth slack --method browser --xoxc-token "$TOKEN" --d-cookie "$COOKIE"
```

Supplying `--xoxc-token` or `--d-cookie` without `--method` also infers browser mode for compatibility. Never combine them with `--method oauth`.

## Revocation

Remove one identity or all Slack credentials locally:

```bash
agentgraph auth remove slack --account 'slack:<team>:<user>'
agentgraph auth remove slack
```

Local removal does not revoke Slack's grant. For OAuth, also revoke the app from Slack's connected-app settings or ask the workspace admin to remove the internal app.
