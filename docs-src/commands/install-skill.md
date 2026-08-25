+++
title = "install-skill"
description = "CLI reference for installing the bundled agentgraph skill."
nav_title = "install-skill"
section = "Reference"
order = 27
summary = "`agentgraph install-skill` installs the bundled agentgraph skill into a user or project agent-skills directory."
output = "commands/install-skill.html"
source_path = "docs-src/commands/install-skill.md"
+++

## Synopsis

```bash
agentgraph install-skill [agentgraph] [--target user|project] [--no-claude] [--force] [--json]
```

The default target is `~/.agents/skills/agentgraph`, with a matching Claude link at
`~/.claude/skills/agentgraph`. A project target installs into `./.agents/skills/agentgraph`
and links `./.claude/skills/agentgraph`. Pass `--no-claude` to skip the Claude link.

The command refuses to replace an existing skill or Claude link unless `--force` is
supplied. The complete skill directory, including progressively loaded references, is
installed together.
