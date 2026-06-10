+++
title = "list_auth_providers_tool"
description = "MCP reference for list_auth_providers_tool."
nav_title = "list_auth_providers_tool"
section = "MCP"
order = 12
summary = "Use `list_auth_providers_tool` to inspect provider-level authentication state, including shared providers such as Google."
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
- authenticated account rows
