# AgentGraph data model

## Entity types

| Type | Contains |
|---|---|
| `Channel` | Chat channels and DM threads. |
| `Document` | Text documents, feed/web pages, Drive files, and Gmail attachment stubs. |
| `Email` | Gmail email threads. |
| `Folder` | Drive folders and RSS feed containers. |
| `Message` | Chat messages. Chat images and uploads are stored in `metadata.attachments`. |
| `Person` | Source identities and confirmed cross-source identity merges. |
| `Spreadsheet` | Google Sheets and other spreadsheet resources. |

The valid core model does not currently include `Task` or `Project`.

## Relationships

Edges connect entities with types such as `authored`, `participated_in`, `posted_in`,
`replied_to`, `mentions`, `contains`, and `references`. Use direct edges when one-hop
context is sufficient and traversal when the investigation needs a bounded subgraph.

## Attachments

Chat photos and file uploads are attachments on `Message` entities. Query them with:

```bash
agentgraph query --type Message --has-attachments --since 7d --json
```

`metadata.attachments` is a JSON array containing `url`, `filename`, `content_type`,
and optional `width` and `height` fields.

Gmail attachments are different: they are `Document` stubs referenced by the owning
`Email`. Re-fetch the email thread, traverse one hop, then download the attachment
document.

## Timestamps and retention

- `created_at`: local graph insertion time.
- `updated_at`: last material change to the stored entity.
- `source_created_at`: source-reported creation or publication time.
- `source_updated_at`: source-reported modification time.
- `synced_at`: last successful connector synchronization.
- `observed_at`: last accepted browser observation of that exact observable entity.

Observable entities expire from `observed_at`, or local `created_at` if never
observed. Messages and Gmail attachment documents follow their parent. Persons remain
while connected. Bookmarks protect an entity from automatic expiration.
