---
# agent-graph-rew7
title: Fix Gmail router to fetch observed threads by ID
status: completed
type: bug
priority: normal
created_at: 2026-03-28T12:26:32Z
updated_at: 2026-03-28T12:33:15Z
---

The Gmail URL router only extracts the account index, ignoring the thread ID in the URL. This causes a generic inbox fetch instead of fetching the specific thread being viewed. Also removes the unimplemented resource_type='inbox' path.\n\n- [x] Update router regex to extract thread IDs from Gmail URLs\n- [x] Change resource_type to 'thread' with thread ID as resource_id\n- [x] Remove/guard the inbox fetch path in GmailConnector.fetch()\n- [x] Add single-thread fetch path in GmailConnector.fetch()

## Summary of Changes\n\nUpdated Gmail router regex to extract the thread/message ID from the URL fragment (handles #inbox/{id}, #search/{query}/{id}, etc). Bare Gmail URLs with no thread selected now return None. GmailConnector.fetch() now only handles resource_type='thread'; removed the unimplemented inbox fetch path and its supporting methods. Added _fetch_thread() which tries threads.get first, then falls back to messages.get to resolve base64url message IDs to their thread ID before fetching.

## Follow-up: URL ID incompatibility\n\nGmail URL IDs (FMfcgzQ... / KtbxL... format) are the web app's proprietary encoding and are rejected by the Gmail API with 'Invalid id value'. Reverted to fetching recent threads by time on each dwell event (with stale check to debounce). Also fixed regex min length (10→16) to exclude Gmail tab labels (promotions=10 chars was matching).
