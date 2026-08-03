+++
title = "RSS"
description = "Configure RSS and Atom feeds in AgentGraph."
nav_title = "RSS"
section = "Configuration"
order = 20
summary = "Add RSS and Atom feeds, import OPML subscriptions, and understand how feed entries appear in the graph."
output = "rss.html"
source_path = "docs-src/rss.md"
+++

AgentGraph can index RSS and Atom feeds without API credentials. Each feed becomes a `Folder` entity, and each article or entry in the feed becomes a `Document` entity linked back to that feed.

RSS feed URLs are stored as connector configuration in `~/.agentgraph/config.toml`
by default, or `~/.agentgraph/config.yaml` if that file exists. They are not stored
in `credentials.json`.

## Install

Install every first-party connector:

```bash
uv sync --extra all
```

Or install only RSS support:

```bash
uv sync --extra rss
```

## Add feeds

Add one or more feed URLs:

```bash
agentgraph connector rss add https://example.com/feed.xml
```

You can also pass an HTML page or local HTML file. AgentGraph validates the page, looks for standard RSS or Atom `<link rel="alternate">` tags, validates the discovered feed, and saves the feed URL:

```bash
agentgraph connector rss add https://example.com/
```

For an interactive setup prompt, use:

```bash
agentgraph auth rss
```

## Remove feeds

Remove one or more exact configured feed URLs:

```bash
agentgraph connector rss remove https://example.com/feed.xml
```

## Import OPML

Import an OPML export from a feed reader:

```bash
agentgraph connector rss import-opml feeds.opml --all
```

To choose specific feeds:

```bash
agentgraph connector rss import-opml feeds.opml --select 1,3-5
```

In an interactive terminal, omit `--all` and `--select` to choose feeds with a checkbox prompt.

## Sync feeds

Run a one-shot ingest for every configured RSS feed:

```bash
agentgraph ingest rss
```

Run RSS polling immediately:

```bash
agentgraph poll rss
```

The RSS connector also polls configured feeds in the background when `agentgraph serve` is running.

## Browser dwell observations

After a feed has been indexed, AgentGraph derives a small set of article URL-prefix patterns
from its known entry links. The browser extension refreshes those patterns periodically and can
then report dwell for matching article pages.

The prefixes are only an extension-side eligibility filter. The server attributes dwell to RSS
only when the observed, normalized URL exactly matches a previously indexed RSS entry. Unknown
pages under a matching prefix are ignored. Configured feed URLs themselves continue to be
supported for dwell observations.

## Query articles

RSS entries are indexed as `Document` entities with `platform=rss`.

```bash
agentgraph query --type Document --filter platform=rss --limit 20
agentgraph search "release notes" --platform rss --limit 10
```

Each article document includes the entry title, summary or content, source link, author metadata when available, and published or updated timestamps when the feed provides them.
