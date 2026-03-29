---
# agent-graph-v3kp
title: Google Sheets connector
status: completed
type: feature
priority: normal
created_at: 2026-03-27T11:57:20Z
updated_at: 2026-03-27T11:58:35Z
---

Add a Google Sheets connector so spreadsheet URLs are ingested into the graph. Needs: gsheets.py connector, router pattern, registry registration, and spreadsheets.readonly OAuth scope.

## Summary of Changes

- agentgraph/connectors/gsheets.py — new GoogleSheetsConnector; fetches spreadsheet metadata and cell values via batchGet (one API call for all sheets), renders each sheet as a labelled tab-separated text block, fetches owner via Drive API
- agentgraph/server/router.py — added _GSHEETS_RE pattern; checked before _GDOCS_RE since both match docs.google.com
- agentgraph/connectors/registry.py — registered GoogleSheetsConnector in bootstrap()
- agentgraph/auth/google.py — added spreadsheets.readonly scope (users will need to re-authenticate)
- agentgraph/auth/google_provider.py — same scope added to GCloudProvider
- agentgraph/server/static/viewer.html — added gsheets to platform filter dropdown
