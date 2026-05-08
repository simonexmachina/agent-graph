---
# agent-graph-m9db
title: Fix SharePoint AllItems.aspx file preview URL handling
status: completed
type: bug
priority: normal
created_at: 2026-05-06T12:14:46Z
updated_at: 2026-05-06T12:16:08Z
---

AllItems.aspx is used by SharePoint for both folder listings and file previews. When id= param points to a file (has extension), _is_folder_url incorrectly returns True, causing GetFolderByServerRelativeUrl to be called on a file path → 403. Fix: detect file preview URLs and fetch via GetFileByServerRelativeUrl instead.

## Summary of Changes

- Fixed `_is_folder_url` to return False when AllItems.aspx `id=` param has a file extension (was treating file preview URLs as folder listings)
- Added `_is_file_preview_url` helper for the symmetric check
- Added `_fetch_file_preview` function: uses `GetFileByServerRelativeUrl` REST API with FedAuth cookies to get file metadata; downloads content for .docx; stores title+web_url for binary files (images, etc.)
- `_fetch_item_sync` now routes AllItems.aspx file previews to `_fetch_file_preview` before the direct download/Graph API paths

The 403 during testing was due to expired FedAuth cookie, not a code issue — confirmed by testing basic REST API access.
