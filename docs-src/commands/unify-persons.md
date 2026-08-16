+++
title = "unify-persons"
description = "CLI reference for merging confirmed duplicate Person entities."
nav_title = "unify-persons"
section = "Reference"
order = 28
summary = "`agentgraph unify-persons` merges duplicate Person entities only after the user confirms that they represent the same human."
output = "commands/unify-persons.html"
source_path = "docs-src/commands/unify-persons.md"
+++

## Synopsis

```bash
agentgraph unify-persons PRIMARY DUPLICATE [DUPLICATE...] [--json]
```

The primary Person keeps its ID. Edges are rewired, identity metadata is folded into
the primary, and duplicate Person entities are removed. Targets accept Person UUIDs,
unambiguous UUID prefixes, or platform references.

Do not run this command based only on a similar display name. Confirm the identities
with the user first.
