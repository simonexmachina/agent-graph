---
# agent-graph-pizo
title: Discord DM support
status: completed
type: feature
priority: normal
created_at: 2026-03-27T12:09:11Z
updated_at: 2026-03-27T12:10:03Z
---

Add support for ingesting Discord Direct Messages (1:1 and group DMs). DM URLs use @me instead of a guild ID: discord.com/channels/@me/{channel_id}. Needs router pattern, connector handling for DM channel type (no guild_id, recipients array instead of name).

## Summary of Changes

- router.py — added _DISCORD_DM_RE for discord.com/channels/@me/{id}; routes to resource_type='dm'
- discord.py — _fetch_channel gains is_dm param; for channel type 1 (DM) and 3 (group DM) builds title from recipients list and emits participated_in edges for each participant; recipients are also added to the module-level user cache
