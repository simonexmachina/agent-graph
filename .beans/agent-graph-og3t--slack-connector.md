---
# agent-graph-og3t
title: Slack connector
status: todo
type: task
priority: normal
created_at: 2026-03-24T10:30:07Z
updated_at: 2026-03-24T10:33:45Z
parent: agent-graph-sb7y
blocked_by:
    - agent-graph-hpnd
---

On dwell of a Slack channel URL: fetch messages via conversations.history (oldest = last fetch timestamp or padding offset). Extract: messages, authors, thread replies (conversations.replies), reactions, mentions. Produce Message entities, Channel entity, Person entities, posted_in/replied_to/mentioned edges. Auth: xoxc- cookie token + d session cookie, extracted from browser DevTools (Application → Cookies → app.slack.com). Both values stored in local config. Sent as Authorization: xoxc-... header + Cookie: d=... on every request. Incremental sync using oldest param. Note: as of March 2026, non-Marketplace apps are rate-limited to 1 req/min with 15 messages max on conversations.history — this may not apply to cookie tokens which behave as user tokens, but treat it conservatively until tested.
