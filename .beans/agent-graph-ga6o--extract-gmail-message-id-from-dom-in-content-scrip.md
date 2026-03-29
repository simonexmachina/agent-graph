---
# agent-graph-ga6o
title: Extract Gmail message ID from DOM in content script
status: completed
type: feature
priority: normal
created_at: 2026-03-28T12:43:04Z
updated_at: 2026-03-28T12:49:45Z
---

Gmail URL tokens (FMfcgzQ...) are Gmail's proprietary encoding, incompatible with the API. The solution is a Gmail content script that extracts the hex message ID from the DOM (data-legacy-message-id attribute), sends it to the background worker, and includes it in focus events so the server can fetch the specific thread via messages.get → threads.get.\n\n- [x] Add content-gmail.ts content script (MutationObserver + message extraction)\n- [x] Update background.ts to cache Gmail message IDs per tab and include in focus events\n- [x] Add meta field to ObserveEvent in event-queue.ts\n- [x] Update manifest.json (content_scripts + host_permissions)\n- [x] Add meta JSONB column to observations table (migration)\n- [x] Update FocusEvent model to accept meta\n- [x] Update app.py to persist meta\n- [x] Update dwell.py to pass meta through to connector dispatch\n- [x] Update BaseConnector.fetch() signature to accept meta\n- [x] Update GmailConnector.fetch() to use meta.gmail_message_id for targeted thread fetch

## Summary of Changes

Added a Gmail content script (content-gmail.ts) that uses MutationObserver to detect when a thread renders and extracts the hex message ID from the data-legacy-message-id DOM attribute. This ID is sent to the background worker via chrome.runtime.sendMessage, cached per-tab, and attached to focus events as meta.gmail_message_id.

The meta field flows through the full stack: ObserveEvent → POST /observe → observations.meta (JSONB) → dwell evaluator → connector.fetch(meta=). GmailConnector.fetch() now uses the message ID to call messages.get → threads.get for an exact thread fetch. Falls back to recent-threads scan when meta is absent.
