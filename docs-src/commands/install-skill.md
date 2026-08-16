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
agentgraph install-skill [AgentGraph] [--target user|project] [--claude] [--force] [--json]
```

The default target is `~/.agents/skills/AgentGraph`. A project target installs into
`./.agents/skills/AgentGraph`. `--claude` also creates the matching link under
`~/.claude/skills` or `./.claude/skills`.

The command refuses to replace an existing skill or Claude link unless `--force` is
supplied. The complete skill directory, including progressively loaded references, is
installed together.
