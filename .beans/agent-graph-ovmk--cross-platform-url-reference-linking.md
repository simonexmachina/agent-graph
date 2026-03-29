---
# agent-graph-ovmk
title: Cross-platform URL reference linking
status: completed
type: feature
priority: normal
created_at: 2026-03-27T12:15:17Z
updated_at: 2026-03-28T00:18:06Z
---

When a Discord message contains a Google Doc/Sheet URL, create a references edge between the message entity and the doc entity. Must work in both directions: forward (message ingested, doc already exists) and backward (doc ingested, messages already reference it).

## Summary of Changes

- agentgraph/graph/link.py — new module with two functions:
  - link_message_to_docs(platform_entity_id, content): extracts Google file IDs from message content, looks up matching entities in DB, creates 'references' edges
  - link_doc_to_messages(platform_entity_id): queries Discord messages whose content contains the file ID, creates 'references' edges back to the doc
- agentgraph/connectors/discord.py — calls _link_google_references() after upsert_batch, which calls link_message_to_docs for each message with content
- agentgraph/connectors/gdocs.py — calls link_doc_to_messages() after upsert_batch
- agentgraph/connectors/gsheets.py — same
