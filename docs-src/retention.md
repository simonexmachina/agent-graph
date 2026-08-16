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

Entities use one of three policies:

| Policy | Entity types | Collection rule |
| --- | --- | --- |
| Observed | `Channel`, `Document`, `Email`, `Folder`, `Spreadsheet` | Delete when `observed_at`, or local `created_at` if never observed, is outside the retention window. |
| Owned | `Message` and Gmail attachment `Document` entities | Delete with the parent Channel or Email. |
| Connected | `Person` | Delete when the Person has no incoming or outgoing edges. |

A stub is not a separate retention category. It follows the policy of the entity it represents. An observable stub begins with `observed_at = NULL`, so its local insertion time controls retention until its own URL is observed.

Google Drive Folder contents are not owned children: a file can remain useful independently or belong to multiple folders. Removing a Folder therefore removes `contains` edges but does not delete its files.

## Expiration

The server runs expiration daily at 03:00 using `AGENTGRAPH_RETENTION_DAYS`, which defaults to 90 days.

To expire entities with a specific retention window, run the standalone script with a
human-readable retention window:

```bash
uv run python scripts/expiration.py --retention 30d
```

The script also accepts minutes, hours, and weeks, such as `30m`, `12h`, and `2w`.
An ISO-8601 timestamp or a date copied from the viewer can be used to calculate the
retention period from a specific date, for example
`--retention 2026-08-01T00:00:00Z` or
`--retention '14/08/2026, 09:51:54'`. Viewer-formatted dates are interpreted in the
script's local timezone. Expiration is applied by default; add `--dry-run` to preview
the number of entities without changing the database.

1. Delete unbookmarked observed-policy entities whose effective retention timestamp is outside the window.
2. Cascade deletion to their unbookmarked owned children.
3. Detach bookmarked owned children before deleting an expired parent.
4. Delete unbookmarked owned entities left without a parent, including detached children after they are unbookmarked.
5. Delete unbookmarked connected-policy Persons that have no edges.

Bookmarks protect an entity from automatic collection. A bookmarked Message or Gmail attachment can remain after its parent is deleted, but it is removed on a later collection run if it is unbookmarked while still detached.

## RSS observations

A configured feed URL identifies the RSS feed `Folder`. The extension reports an observation after the exact configured URL matches an observation pattern. The RSS connector maps that URL to the stored `feed/{feed_hash}` Folder, and AgentGraph sets that Folder's `observed_at`.

Article observation is stricter than the extension's URL-prefix filter:

1. AgentGraph derives a small set of eligible URL prefixes from indexed RSS entry links.
2. The extension may report observation for a page matching one of those prefixes.
3. The server normalizes the URL and requires an exact match with the `web_url` of an existing RSS `Document`.
4. Only the matched Document receives `observed_at`; unknown pages under the same prefix are ignored.

RSS polling and article hydration can change content, source dates, `updated_at`, and `synced_at`, but they do not extend observation-based retention. Bookmark a configured feed Folder if it should remain indefinitely without being opened in the browser.

## Connector entity behavior

Every `created_at` value below is the non-null local insertion time. Connector source dates are stored separately in `source_created_at` and `source_updated_at`; they never replace the local timestamp.

### Slack

| Entity type | `observed_at` | `created_at` | Expiration |
| --- | --- | --- | --- |
| `Channel` | Set when its Slack channel URL is observed. | Set when first inserted, including as a stub. | According to target type: observed policy using `COALESCE(observed_at, created_at)`. |
| `Message` | Not set directly; observation of its parent Channel determines retention. | Set when first inserted. | Owned by its Channel and deleted with it, subject to bookmark detachment. |
| `Person` | Not set directly; Channel observations preserve it through graph edges. | Set when first inserted. | Connected policy; deleted only after all edges are gone. |

### Discord

| Entity type | `observed_at` | `created_at` | Expiration |
| --- | --- | --- | --- |
| `Channel` | Set when its Discord channel URL is observed. | Set when first inserted, including as a stub. | According to target type: observed policy using `COALESCE(observed_at, created_at)`. |
| `Message` | Not set directly; observation of its parent Channel determines retention. | Set when first inserted. | Owned by its Channel and deleted with it, subject to bookmark detachment. |
| `Person` | Not set directly; Channel observations preserve it through graph edges. | Set when first inserted. | Connected policy; deleted only after all edges are gone. |

### Gmail

| Entity type | `observed_at` | `created_at` | Expiration |
| --- | --- | --- | --- |
| `Email` | Set when its Gmail thread URL is observed. | Set when first inserted, including as a stub. | According to target type: observed policy using `COALESCE(observed_at, created_at)`. |
| Attachment `Document` | Not set directly; observation of its parent Email determines retention. | Set when its attachment stub is first inserted. | Owned by its Email and deleted with it, subject to bookmark detachment. |
| `Person` | Not set directly; Email observations preserve it through graph edges. | Set when first inserted. | Connected policy; deleted only after all edges are gone. |

### Google Drive

| Entity type | `observed_at` | `created_at` | Expiration |
| --- | --- | --- | --- |
| `Folder` | Set when its exact Drive folder URL is observed. | Set when first inserted, including as a stub. | According to target type: observed policy using `COALESCE(observed_at, created_at)`. Deletion removes `contains` edges, not contained entities. |
| `Document` | Set when its exact Drive file URL is observed. | Set when first inserted, including as a stub. | According to target type: observed policy using `COALESCE(observed_at, created_at)`. |
| Google Docs/Sheets child stub | Set only when the stub's own URL is later observed by its target connector. | Set when the Folder listing first inserts the stub. | According to target type (`Document` or `Spreadsheet`), not according to the containing Folder. |
| `Person` | Not set directly; observations preserve it through graph edges. | Set when first inserted. | Connected policy; deleted only after all edges are gone. |

### Google Docs

| Entity type | `observed_at` | `created_at` | Expiration |
| --- | --- | --- | --- |
| `Document` | Set when its exact Google Docs URL is observed. | Set when first inserted, including as a stub. | According to target type: observed policy using `COALESCE(observed_at, created_at)`. |
| `Person` | Not set directly; Document observations preserve it through graph edges. | Set when first inserted. | Connected policy; deleted only after all edges are gone. |

### Google Sheets

| Entity type | `observed_at` | `created_at` | Expiration |
| --- | --- | --- | --- |
| `Spreadsheet` | Set when its exact Google Sheets URL is observed. | Set when first inserted, including as a stub. | According to target type: observed policy using `COALESCE(observed_at, created_at)`. |
| `Person` | Not set directly; Spreadsheet observations preserve it through graph edges. | Set when first inserted. | Connected policy; deleted only after all edges are gone. |

### RSS

| Entity type | `observed_at` | `created_at` | Expiration |
| --- | --- | --- | --- |
| Feed `Folder` | Set when the exact configured feed URL resolves to that feed and is observed. | Set when the feed is first inserted. | According to target type: observed policy using `COALESCE(observed_at, created_at)`. |
| Entry `Document` | Set when its article URL resolves to that RSS entry and is observed. | Set when the entry is first inserted, before optional hydration. | According to target type: observed policy using `COALESCE(observed_at, created_at)`. |
| `Person` | Not set directly; feed and entry observations preserve it through graph edges. | Set when first inserted. | Connected policy; deleted only after all edges are gone. |

### Web

| Entity type | `observed_at` | `created_at` | Expiration |
| --- | --- | --- | --- |
| `Document` | Set when its exact recognized web URL is observed. | Set when first inserted, including through `ingest`, `fetch`, or `fetch-entity`. | According to target type: observed policy using `COALESCE(observed_at, created_at)`. |
