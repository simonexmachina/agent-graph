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

## Push release tags one at a time

Push each release tag in its own `git push`, and confirm the run started before
pushing the next:

```bash
git push origin agentgraph-connector-web-v0.5.6
gh run list --workflow "PyPI Release" --limit 1
```

GitHub drops push events when a single push carries more than a few tags, so
`git push origin tagA tagB tagC tagD tagE` can silently publish nothing. Push
connector tags before the server tag: while a new server version is missing from
PyPI, installs simply resolve to the previous release, whereas a published server
whose connector floor cannot be satisfied makes that version uninstallable.

If a tag event was missed, do not delete and re-push the tag — re-pushing an
existing ref fires no event. Run the workflow manually instead, naming the tag:

```bash
gh workflow run "PyPI Release" --ref main -f tag=agentgraph-connector-web-v0.5.6
```

The dispatch takes its workflow definition from `--ref` but checks out the tag
itself, so the distribution is built from the tagged tree. Dispatching only works
for tags whose workflow the `workflow_dispatch` trigger predates; for older tags,
re-release at the next patch version. Orphaned tags are inert either way, because
`scripts/release_package.py` rejects a tag whose version no longer matches the
package metadata.
