# /slack-auth — Slack Browser Auth Skill

Use `agent-browser` to extract Slack credentials from an open browser session and save them non-interactively.

## Prerequisites

Load the agent-browser skill before running any commands:

```bash
agent-browser skills get agent-browser
```

## Steps

### 1. Verify current auth status

```bash
agentgraph connectors --json | jq '.[] | select(.source == "slack") | {auth_status, auth_detail}'
```

If `auth_status` is `"ok"`, credentials are already valid — confirm with the user before overwriting.

### 2. Connect to Slack

First ask the user if they use Google to login to Slack, because Google may block sign-in from agent-browser's bundled "Google Chrome for Testing" with "This browser or app may not be secure." If they use Google to login, open regular Chrome with remote debugging enabled:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir=/private/tmp/agentgraph-slack-auth-chrome
agent-browser connect 9222
```

Otherwise, use agent-browser to open Slack's workspace sign-in flow:

```bash
agent-browser --headed open https://app.slack.com/workspace-signin
```

Confirm you're on a Slack workspace page (not the login screen) with a snapshot:

```bash
agent-browser wait 3000
agent-browser snapshot -i
```

Then ask the user to login to Slack and wait to proceed.

### 3. Extract the xoxc token

Slack stores auth tokens in `localStorage`. Prefer the team ID from the current `/client/T...` URL so this works across workspaces:

```bash
TEAM_ID=$(agent-browser get url | sed -n 's#.*app\.slack\.com/client/\(T[A-Z0-9]*\).*#\1#p')
TOKEN=$(agent-browser eval "(() => { const cfg = JSON.parse(localStorage.getItem('localConfig_v2')); const team = '$TEAM_ID' || Object.keys(cfg.teams || {})[0]; return cfg.teams[team].token; })()" | jq -r .)
```

The decoded token should start with `xoxc-`. If `TEAM_ID` is empty, navigate into a Slack workspace first:

```bash
agent-browser snapshot -i   # find the workspace link
agent-browser click @e<n>   # click into the workspace
agent-browser wait 2000
# then retry the eval above
```

### 4. Extract the d cookie

Use the actual `d` cookie. Do not use `d-s` for the CLI's `--d-cookie` value; `agentgraph auth slack` sends it as `d=<value>`.

```bash
COOKIE=$(agent-browser --json cookies get | jq -r '.data.cookies[] | select(.name == "d" and (.domain | contains("slack"))) | .value' | head -n 1)
```

If you need to inspect cookie availability without printing values:

```bash
agent-browser --json cookies get | jq '[.data.cookies[] | select(.domain | contains("slack")) | {name, domain}]'
```

### 5. Save the credentials

```bash
if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then echo "missing token" >&2; exit 1; fi
if [ -z "$COOKIE" ] || [ "$COOKIE" = "null" ]; then echo "missing d cookie" >&2; exit 1; fi
case "$TOKEN" in xoxc-*) ;; *) echo "token did not decode to xoxc prefix" >&2; exit 1;; esac
agentgraph auth slack --xoxc-token "$TOKEN" --d-cookie "$COOKIE"
```

The CLI verifies against `slack.com/api/auth.test` and prints the authenticated user ID.

### 6. Verify

```bash
agentgraph connectors --json | jq '.[] | select(.source == "slack")'
```

Expect `"auth_status": "ok"` with a user ID in `auth_detail`.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `connect 9222` fails | Chrome isn't running with CDP — use `agent-browser open https://app.slack.com/workspace-signin` instead |
| Google says "This browser or app may not be secure" | The browser is likely Google Chrome for Testing. Use regular Chrome with `--remote-debugging-port=9222`, then `agent-browser connect 9222`. |
| `localConfig_v2` eval returns null | User isn't in a workspace — take a snapshot and navigate into one first |
| Cookie named `d` not found | Confirm the user is logged into `app.slack.com`; do not substitute `d-s` unless the CLI is changed to send it as `d-s=<value>`. |
| `auth.test` returns `invalid_auth` | The d cookie is expired — re-extract from a fresh browser session |
| Multiple workspaces in token | Use the team ID from the current `/client/T...` URL; `Object.keys(cfg.teams)` is only a fallback |
