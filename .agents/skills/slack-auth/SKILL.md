---
name: slack-auth
description: Authenticate AgentGraph to Slack with official user OAuth PKCE by default, or explicitly use browser-session credentials as a fallback.
---

# /slack-auth - Slack Authentication

Use official Slack user OAuth unless the user explicitly requests the browser-session fallback.

## OAuth (default)

1. Check status without exposing credentials:

```bash
agentgraph auth status --json | jq '.[] | select(.provider == "slack")'
```

2. Confirm `AGENTGRAPH_SLACK_CLIENT_ID` is set for the admin-created internal app. The app must use the AgentGraph manifest and register the exact redirect URI. The default is `http://localhost:8766/slack/oauth/callback`; `AGENTGRAPH_SLACK_REDIRECT_URI` may override it.

3. Start OAuth and let the user approve in the opened browser:

```bash
agentgraph auth slack
```

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
