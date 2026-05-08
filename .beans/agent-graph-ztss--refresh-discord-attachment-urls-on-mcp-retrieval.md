---
# agent-graph-ztss
title: Refresh Discord attachment URLs on MCP retrieval
status: completed
type: bug
priority: normal
created_at: 2026-05-04T15:12:56Z
updated_at: 2026-05-04T15:14:32Z
---

Discord CDN URLs contain expiring signed tokens. Refresh them lazily via GET /channels/{channel_id}/messages/{message_id} when Discord Message entities with attachments are returned by MCP tools.

## Summary of Changes

- Added refresh_attachment_urls(channel_id, message_id, stored_json) to the connector package — calls GET /channels/{channel_id}/messages/{message_id}, rebuilds attachments via _extract_attachments, falls back to stored_json on any error
- Added _refresh_discord_attachments(results) helper in MCP server — filters to Discord Message entities, refreshes concurrently via asyncio.gather
- Called in both query_by_filter_tool and search_entities_tool before serialising results
- Docstrings updated to note URLs are valid at call time
