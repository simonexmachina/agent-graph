+++
title = "Release packages"
nav_title = "Release packages"
nav_hidden = true
section = "Reference"
order = 32
summary = "Publish the server and connectors as independently versioned PyPI distributions."
description = "Maintainer procedure for publishing AgentGraph packages independently."
output = "releasing.html"
source_path = "docs-src/releasing.md"
+++

# Release packages

AgentGraph publishes the server and each connector as independently versioned
PyPI distributions. Use Semantic Versioning for the package being released:
bump its patch version for compatible fixes, its minor version for compatible
features, and its major version for incompatible changes.

Before releasing, update that package's `pyproject.toml` version and refresh
`uv.lock`. Update internal dependency ranges only when the package requires a
newer dependency release or is incompatible with an older one. The RSS
connector's web connector range is maintained the same way.

Run the standard quality gates:

```bash
uv run pytest tests/ -m "not integration and not browser" -q
uv run pyright
uv run ruff check agentgraph/ packages/ scripts/ tests/
```

Commit and push the version change on `main`. Create an annotated tag whose
package name and version match the package metadata exactly:

```bash
git tag -a agentgraph-server-v0.5.4 -m "Release agentgraph-server v0.5.4"
git push origin agentgraph-server-v0.5.4
```

For connectors, use the PyPI distribution name, for example
`agentgraph-connector-slack-v0.5.4`. The PyPI Release workflow validates the
tag, builds and validates only that distribution, then publishes it. Existing
unqualified `vX.Y.Z` tags are historical and do not start a package release.
