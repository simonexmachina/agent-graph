+++
title = "list_auth_providers_tool"
description = "MCP reference for list_auth_providers_tool."
nav_title = "list_auth_providers_tool"
section = "MCP"
order = 12
summary = "Use `list_auth_providers_tool` to inspect credential-backed provider authentication state, including shared providers such as Google."
output = "mcp/list-auth-providers.html"
source_path = "docs-src/mcp/list-auth-providers.md"
+++

## Signature

```text
list_auth_providers_tool() -> JSON string
```

## Returns

- provider key and description
- connector sources that use the provider
- shared-provider flag
- `auth_status` and `auth_detail`
- authenticated account rows, including `auth_method`

Connectors that only need configuration, such as RSS, and connectors that need
no setup, such as generic web, are omitted. Use `list_connectors_tool` to
inspect all installed connectors.
