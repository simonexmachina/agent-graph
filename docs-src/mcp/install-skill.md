+++
title = "install_skill_tool"
description = "MCP reference for install_skill_tool."
nav_title = "install_skill_tool"
section = "MCP"
order = 14
summary = "Use `install_skill_tool` to install the bundled AgentGraph skill into a user or project agent-skills directory."
output = "mcp/install-skill.html"
source_path = "docs-src/mcp/install-skill.md"
+++

## Signature

```text
install_skill_tool(skill="AgentGraph", target="user", force=false, claude=true) -> JSON string
```

## Arguments

- `skill`: bundled skill name; currently `AgentGraph`
- `target`: `user` for `~/.agents/skills` or `project` for `./.agents/skills`
- `force`: replace an existing destination
- `claude`: link the installed skill into the corresponding Claude skills directory; defaults to `true`

The complete skill directory, including progressively loaded references, is copied.
The result reports both destinations and whether an existing skill was replaced.
