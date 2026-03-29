---
# agent-graph-plwx
title: 'Service worker: focus/blur event emitter'
status: completed
type: task
priority: normal
created_at: 2026-03-24T10:19:19Z
updated_at: 2026-03-24T11:18:02Z
parent: agent-graph-4q2a
---

background.js service worker. Listen to tabs.onActivated, tabs.onUpdated, tabs.onRemoved, windows.onFocusChanged. Emit FocusEvent / BlurEvent to localhost. No timers, no DOM access. Use event-queue.js for batching (blur=immediate, focus=2s batch). In-memory queue (max 500) if server unavailable.
