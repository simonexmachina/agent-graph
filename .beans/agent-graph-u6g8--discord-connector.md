---
# agent-graph-u6g8
title: Discord connector
status: scrapped
type: task
priority: normal
created_at: 2026-03-24T10:20:05Z
updated_at: 2026-03-24T10:29:45Z
parent: agent-graph-sb7y
blocked_by:
    - agent-graph-hpnd
---

On dwell: fetch channel messages via Discord REST API (GET /channels/{id}/messages). Extract: messages, authors, threads, reactions, mentions. Produce Message entities, Person entities, posted_in edges, replied_to edges. Bot token auth. Incremental: use before/after snowflake IDs.

## Reasons for Scrapping

Replaced by Slack as the second MVP connector. Discord was in the initial plan because the browser extension spec mentioned it as an example, but Slack is more relevant for enterprise use and has better API support for the MVP.
