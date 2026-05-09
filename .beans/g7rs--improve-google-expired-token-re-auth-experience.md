---
# g7rs
title: Improve Google expired-token re-auth experience
status: completed
type: bug
priority: normal
created_at: 2026-05-09T13:53:45Z
updated_at: 2026-05-09T13:57:40Z
---

Implemented CLI-first Google expired-token re-auth recovery. Google auth verification now distinguishes missing credentials, missing refresh tokens, rejected refresh tokens, and valid credentials. The OAuth flow explains invalid saved credentials and reuses stored OAuth client ID/secret. Added auth/CLI tests and updated the /graph skill guidance.
