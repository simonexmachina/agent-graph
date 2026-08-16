+++
title = "Entity retention"
description = "How AgentGraph observations, timestamps, bookmarks, and expiration determine entity retention."
nav_title = "Retention"
section = "Reference"
order = 5
summary = "Understand which entities expire by observation time, which follow a parent, and which remain only while connected to the graph."
output = "retention.html"
source_path = "docs-src/retention.md"
+++

AgentGraph treats browser observation, connector synchronization, and source-system dates as separate events. Fetching or changing an entity does not imply that you observed it.

## Entity timestamps

| Column | Meaning |
| --- | --- |
| `created_at` | Local graph insertion time. Always present and never changes. |
| `updated_at` | Last material change to stored entity data. Always present. |
| `source_created_at` | Creation or publication time reported by the source, when available. |
| `source_updated_at` | Modification time reported by the source, when available. |
| `synced_at` | Last successful connector synchronization. Null for unresolved stubs. |
| `observed_at` | Last accepted browser observation of this exact entity. Null until observed. |

Ingests, background polls, explicit `fetch` and `fetch-entity` commands, stub creation, source changes, and new graph edges do not set `observed_at`. The browser sends an observation report only after its observation threshold has elapsed. AgentGraph then fetches and persists the resource and records `observed_at`. Duration-only updates do not fetch the resource or change `observed_at`.

## Retention policies

Entities use one of four policies:

| Policy | Entity types | Collection rule |
| --- | --- | --- |
| Observed | `Channel`, `Document`, `Email`, `Folder`, `Spreadsheet` | Delete when `observed_at` (or `created_at` if never observed) is outside the retention window. |
| Owned | `Message` and Gmail attachment `Document` entities | Delete with the parent Channel or Email. |
| Connected | `Person` | Delete when the Person has no incoming or outgoing edges. |
| Persistent | Configured RSS feed `Folder` entities | Never delete automatically. |

A stub is not a separate retention category. It follows the policy of the entity it represents. An observable stub begins with `observed_at = NULL`, so its local insertion time controls retention until its own URL is observed.

Google Drive Folder contents are not owned children: a file can remain useful independently or belong to multiple folders. Removing a Folder therefore removes `contains` edges but does not delete its files.

## Bookmarking

Bookmarking an entity protects it from being removed when it expires. A bookmarked Message or Gmail attachment can remain after its parent is deleted.

## Expiration

The server runs expiration daily at 03:00:

1. Delete unbookmarked observed-policy entities whose effective retention timestamp is outside the window.
2. Cascade deletion to their unbookmarked owned children.
3. Detach bookmarked owned children before deleting an expired parent.
4. Delete unbookmarked owned entities left without a parent, including detached children after they are unbookmarked.
5. Delete unbookmarked connected-policy Persons that have no edges.

The retention period is controlled using `AGENTGRAPH_RETENTION_DAYS`, which defaults to 90 days.

## RSS observations

Configured RSS feeds are persistent source Folders. They are not observable and do not expire automatically. Removing a feed with `agentgraph connector rss remove` deletes its Folder and feed edges, while its articles remain subject to their normal retention.

Article observation is stricter than the extension's URL-prefix filter:

1. AgentGraph derives a small set of eligible URL prefixes from indexed RSS entry links.
2. The extension may report observation for a page matching one of those prefixes.
3. The server normalizes the URL and requires an exact match with the `web_url` of an existing RSS `Document`.
4. Only the matched Document receives `observed_at`; unknown pages under the same prefix are ignored.

RSS polling and article hydration can change content, source dates, `updated_at`, and `synced_at`, but they do not extend article observation-based retention.
