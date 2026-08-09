+++
title = "authenticate_provider_tool"
description = "MCP reference for authenticate_provider_tool."
nav_title = "authenticate_provider_tool"
section = "MCP"
order = 13
summary = "Use `authenticate_provider_tool` to dispatch a provider's connector-owned authentication flow."
output = "mcp/authenticate-provider.html"
source_path = "docs-src/mcp/authenticate-provider.md"
+++

## Signature

```text
authenticate_provider_tool(provider, args = null, account_id = null, add = false) -> JSON string
```

## Arguments

- `provider`: auth provider key, such as `google`, `slack`, or `discord`
- `args`: connector-owned options; Slack accepts `--method oauth|browser`,
  `--xoxc-token`, and `--d-cookie`
- `account_id`: optional existing identity to replace
- `add`: add another identity and make it the default

Slack OAuth is interactive and waits for the local PKCE callback. Browser credential
arguments select the explicit fallback. The result reports `authenticated: true` or
an error string.
