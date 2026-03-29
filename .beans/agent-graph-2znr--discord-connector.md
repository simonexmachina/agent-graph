---
# agent-graph-2znr
title: Discord connector
status: completed
type: feature
priority: normal
created_at: 2026-03-27T11:03:05Z
updated_at: 2026-03-27T11:05:38Z
---

Add a Discord connector: bot token auth, channel/thread message fetch, person identity, dwell detection on discord.com/channels URLs. Include agentgraph auth discord command and add Discord to the onboard step.

## Summary of Changes

- agentgraph/auth/credentials.py: added DiscordCredentials model + discord field on Credentials
- agentgraph/auth/discord.py: run_token_flow() — guides user through bot creation, verifies token via /users/@me
- agentgraph/connectors/discord.py: DiscordConnector — channel fetch, snowflake timestamps, thread replies, person/edge extraction
- agentgraph/connectors/registry.py: DiscordConnector registered in bootstrap()
- agentgraph/server/router.py: discord.com/channels/{guild}/{channel} URL pattern
- agentgraph/cli.py: auth discord command + Discord added to onboard (Step 3/3)
- README.md: auth instructions and connector table updated
