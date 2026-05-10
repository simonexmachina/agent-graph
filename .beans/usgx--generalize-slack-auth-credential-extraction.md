---
# usgx
title: Generalize Slack auth credential extraction
status: completed
type: task
priority: normal
created_at: 2026-05-10T10:11:09Z
updated_at: 2026-05-10T10:11:09Z
---

Updated slack-auth skill to extract the team ID from the current /client/T... URL, jq-decode the xoxc token from agent-browser eval output, and use the actual d cookie rather than d-s when saving credentials.
