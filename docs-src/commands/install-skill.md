+++
title = "install-skill"
description = "CLI reference for installing the bundled AgentGraph skill."
nav_title = "install-skill"
section = "Reference"
order = 27
summary = "`agentgraph install-skill` installs the bundled AgentGraph skill into a user or project agent-skills directory."
output = "commands/install-skill.html"
source_path = "docs-src/commands/install-skill.md"
+++

## Synopsis

```bash
agentgraph install-skill [AgentGraph] [--target user|project] [--no-claude] [--force] [--json]
```

The default target is `~/.agents/skills/AgentGraph`, with a matching Claude link at
`~/.claude/skills/AgentGraph`. A project target installs into `./.agents/skills/AgentGraph`
and links `./.claude/skills/AgentGraph`. Pass `--no-claude` to skip the Claude link.

The command refuses to replace an existing skill or Claude link unless `--force` is
supplied. The complete skill directory, including progressively loaded references, is
installed together.
