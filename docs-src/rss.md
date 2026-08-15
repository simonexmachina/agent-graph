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

AgentGraph validates every supplied URL as an RSS or Atom feed before saving it.
HTML pages and invalid feeds are rejected without changing the connector
configuration. A successful add queues an RSS poll immediately.

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

## Browser observations

Configured feed URLs and, after indexing, a small set of article URL-prefix patterns derived
from known entry links are exposed to the browser extension. The extension refreshes those
patterns periodically and can then report observation for matching feed and article pages.

The prefixes are only an extension-side eligibility filter. The server attributes observations to RSS
only when the observed, normalized URL exactly matches a configured feed or previously indexed
RSS entry. Unknown pages under a matching article prefix are ignored.

Observing the exact configured feed URL updates the feed `Folder`, whose stored ID is derived as
`feed/{feed_hash}`. Observing an article URL updates only the existing RSS `Document` whose
`metadata.web_url` exactly matches the normalized URL. Polling and hydration do not count as
observations or extend observation-based retention. See [Entity retention](retention.html).

## Query articles

RSS entries are indexed as `Document` entities with `platform=rss`.

```bash
agentgraph query --type Document --filter platform=rss --limit 20
agentgraph search "release notes" --platform rss --limit 10
```

Each article document includes the entry title, summary or content, source link, author metadata when available, and published or updated timestamps when the feed provides them.

## Article authors

Feed authors — Atom `<author>`, RSS `<author>`, and `<dc:creator>` — become `Person` entities. Every
author credited by the feed or one of its entries is linked to the feed `Folder`, and authors are
linked to their articles, by `authored` edges. Entries that declare no author of their own inherit
the feed-level author, per the Atom spec. Authors are identified by email address when the feed
supplies one and by name otherwise, so a name-only author is shared across every feed that credits
that name.

```bash
agentgraph search "Matt Ridley" --type Person
agentgraph edges <person-id>
```
