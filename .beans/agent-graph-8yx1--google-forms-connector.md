---
# agent-graph-8yx1
title: Google Forms connector
status: completed
type: feature
priority: normal
created_at: 2026-03-29T11:48:58Z
updated_at: 2026-03-29T12:48:53Z
---

Add support for fetching Google Forms: connector, URL routing, registry, and tests. Forms URL pattern: https://docs.google.com/forms/d/{formId}/...

## Summary of Changes

- **agentgraph/connectors/gforms.py**: New `GoogleFormsConnector` — fetches form structure (title, description, questions with types/options) via Forms API v1; renders as searchable plain text; 15-minute stale policy; Drive API owner lookup
- **agentgraph/server/router.py**: Regex pattern for `docs.google.com/forms/d/{formId}` URLs, checked before Sheets/Docs
- **agentgraph/connectors/registry.py**: `GoogleFormsConnector` registered at startup
- **agentgraph/graph/fetch.py**: Added `"Form" → "form"` to resource_type_map
- **agentgraph/connectors/base.py**: Added `ResourceType` Literal type alias
- **agentgraph/auth/google_provider.py**: Added `forms.body.readonly` scope to GCloudProvider
- **agentgraph/connectors/gdocs.py**: Added `_extract_plain_text` and `_extract_persons` helpers (expected by pre-existing tests)
- **tests/**: Connector fetch-policy tests and router URL classification tests (36 passing)
