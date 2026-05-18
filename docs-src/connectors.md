+++
title = "Connectors"
description = "Supported AgentGraph connectors, fetch behavior, and the connector authoring contract."
nav_title = "Connectors"
section = "Reference"
order = 20
summary = "Connectors turn external systems into graph entities, people, and edges. The first half of this page is operational reference; the second half is the author guide."
output = "connectors.html"
source_path = "docs-src/connectors.md"
+++

## Supported connectors

<table>
  <thead>
    <tr>
      <th>Source</th>
      <th>Entities</th>
      <th>Auth</th>
      <th>Refresh model</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Slack</td>
      <td>Channel, Message</td>
      <td>Browser-derived cookie credentials</td>
      <td>Browser dwell plus 5 minute polling</td>
    </tr>
    <tr>
      <td>Discord</td>
      <td>Channel, Message</td>
      <td>Bot token</td>
      <td>Browser dwell plus 5 minute polling</td>
    </tr>
    <tr>
      <td>Google Docs</td>
      <td>Document</td>
      <td>Google OAuth</td>
      <td>Browser dwell plus Drive-backed refresh</td>
    </tr>
    <tr>
      <td>Google Sheets</td>
      <td>Spreadsheet</td>
      <td>Google OAuth</td>
      <td>Browser dwell plus Drive-backed refresh</td>
    </tr>
    <tr>
      <td>Google Drive</td>
      <td>Folder, Document</td>
      <td>Google OAuth</td>
      <td>Browser dwell for folders and files, plus Drive changes polling</td>
    </tr>
    <tr>
      <td>Gmail</td>
      <td>Thread</td>
      <td>Google OAuth</td>
      <td>Browser dwell plus background poll and ingest</td>
    </tr>
  </tbody>
</table>

## Connector behavior

- **Browser dwell:** supported URLs trigger targeted fetches after the configured dwell threshold.
- **Polling:** connectors that support it store cursor state and fetch changes on a schedule.
- **Ingest:** some connectors expose a broader one-shot historical ingest beyond poll behavior.
- **Download metadata:** file-backed entities can expose `metadata.download_url` and `metadata.mime_type` when an agent needs source bytes.

## Authoring a connector

A connector is a Python package that subclasses `BaseConnector`, implements the required fetch path, and registers itself through the `agentgraph.connectors` entry point group.

### Base contract

The required shape is small: identify which URLs the connector owns, implement `fetch()`, and optionally implement polling, ingest, auth, and user identity hooks.

```python
class MyConnector(BaseConnector):
    source = "myplatform"
    url_patterns = ["https://app.example.com/*"]
    auth_label = "myplatform"
    auth_description = "Example platform"

    def can_handle(self, url: str) -> bool:
        return "app.example.com" in url

    async def fetch(
        self,
        resource_type: ResourceType,
        resource_id: str,
        meta: dict[str, str] | None = None,
    ) -> EntityBatch:
        ...
```

### Output model

- `EntityRecord` for messages, documents, channels, folders, spreadsheets, and threads.
- `PersonRecord` for authors and participants.
- `EdgeRecord` for authored, posted-in, replied-to, mentions, references, and similar relationships.

### Packaging

Register the connector in `pyproject.toml`.

```toml
[project.entry-points."agentgraph.connectors"]
myplatform = "agentgraph_connector_myplatform:MyConnector"
```
