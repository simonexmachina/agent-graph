# Building a unified knowledge graph from SaaS platforms for AI agents

**The fastest path to a local, AI-queryable knowledge graph across 12 SaaS platforms combines Nango for auth/sync orchestration, PostgreSQL with pgvector for hybrid storage, and MCP/Agent Skills/CLI as the agent interface.** Every platform in scope exposes sufficient API surface for a 3-month rolling context window, though real-time capabilities vary dramatically — Slack, GitHub, and Salesforce offer excellent event-driven sync, while Workday requires polling as the sole integration pattern. The core architectural challenge is not connecting to any single API but building the cross-platform identity resolution and relationship extraction layer that transforms siloed data into a traversable graph. This report provides endpoint-level detail for all 12 platforms, a production-ready schema, and a concrete connector architecture.

---

## Communications platforms: Slack and Microsoft Teams

### Slack

Slack exposes over **200 methods** through its HTTP RPC-style Web API at `https://slack.com/api/`. The platform also offers an Events API for push-based event delivery and Socket Mode for WebSocket-based connections behind firewalls.

**Key endpoints for a knowledge worker context:**

| Method | Purpose | Rate Tier |
|---|---|---|
| `conversations.history` | Channel messages with `oldest`/`latest` timestamps | Tier 3 (50+/min) |
| `conversations.replies` | Thread replies by parent `ts` | Tier 3 |
| `conversations.list` | List all channels (cursor-paginated) | Tier 2 (20+/min) |
| `users.list` / `users.info` | User profiles including email | Tier 2 / Tier 4 |
| `files.list` | Shared files | Tier 3 |
| `search.messages` | Full-text search (user token only) | Special |

**Authentication** uses OAuth 2.0 with bot tokens (`xoxb-`) as the standard pattern for connectors. Tokens do not expire by default. Critical scopes: `channels:history`, `groups:history`, `users:read`, `users:read.email`, `files:read`, `reactions:read`. The `search:read` scope requires a user token — bot tokens cannot search.

**Rate limits** follow a 4-tier system per method per workspace. Tier 3 methods (the most important for sync) allow **50+ requests/minute**. A critical change took effect March 2026: non-Marketplace apps now see `conversations.history` restricted to **1 request/minute with 15 messages max**. Internal custom-built apps and Marketplace apps retain full Tier 3 access.

**Real-time sync** via the Events API supports subscribing to `message.channels`, `message.groups`, `reaction_added`, `file_shared`, `member_joined_channel`, `team_join`, and dozens more events. Socket Mode provides WebSocket delivery without requiring a public endpoint — ideal for local development. Events are delivered at up to **30,000/workspace/app/60 minutes**.

**Incremental sync** uses `conversations.history` with `oldest` set to the last-seen timestamp. For a typical workspace (500 users, 200 channels, 500 messages/day), initial 3-month backfill requires ~5,300 API calls (~2 hours), and daily incremental sync needs only ~105 calls.

### Microsoft Teams

Teams data flows through the **Microsoft Graph API** at `https://graph.microsoft.com/v1.0/`. Message access is significantly more complex than Slack due to the metered API model.

**Key endpoints:**

| Endpoint | Purpose |
|---|---|
| `GET /teams/{id}/channels/{id}/messages` | Channel messages (no timestamp filter) |
| `GET /teams/{id}/channels/getAllMessages?$filter=lastModifiedDateTime gt {dt}` | Filtered messages (**metered API** — requires licensing) |
| `GET /chats/{id}/messages/delta` | Delta query for chat messages |
| `GET /users` | Directory users |

**Authentication** uses Azure AD OAuth 2.0 with the client credentials flow for service/daemon applications. Key application permissions: `ChannelMessage.Read.All`, `Chat.Read.All`, `User.Read.All`. All application permissions require **tenant admin consent**. Certificate-based auth is preferred over client secrets in production.

**Rate limits**: Teams-specific limits are **4 requests/second per app per team** and **1 request/second per channel or chat**. The global Graph limit is 130,000 requests/10 seconds per app across all tenants. The tenant-wide subscription limit is **10,000 active subscriptions** across all Teams resources.

**Real-time sync** uses the Graph subscriptions API. You can subscribe to `/teams/{id}/channels/{id}/messages` or tenant-wide `/teams/getAllMessages` (metered). Subscriptions expire in **60 minutes** without a lifecycle notification URL. Rich notifications (with encrypted payload) are available for chat messages. Microsoft explicitly states apps **should not poll the same resource more than once per day** — change notifications are the expected primary mechanism.

**The critical gotcha**: `getAllMessages` is a metered/licensed API requiring Teams API licensing (model=A or model=B pricing). Without this license, building a comprehensive Teams connector is substantially more expensive and complex than Slack.

---

## Collaboration and docs: Google Workspace and Microsoft 365

### Google Workspace (Drive, Docs, Sheets, Slides)

**Google Drive API v3** at `https://www.googleapis.com/drive/v3` is the backbone for file sync. Rate limits are generous: **12,000 queries per 60 seconds** per project and per user, with no daily cap. The `changes.list` endpoint with `pageToken` provides efficient incremental sync — each call returns only files modified since the last token.

**Push notifications** work via `changes.watch` (all Drive changes) and `files.watch` (individual files). Channels expire after **7 days max** for changes, **1 day** for files, with no auto-renewal. Notification payloads contain only headers (no body) — you must call `changes.list` to get actual change details.

**Google Docs API v1** at `https://docs.googleapis.com/v1` returns the full document structure as deeply nested JSON (paragraphs, tables, lists, inline objects). Rate limits are tighter: **3,000 read requests/minute per project**, **300 per user**. The Docs API has **no native webhook support** — detect changes via Drive's `files.watch`, then fetch the document content.

**Gmail API** uses Google Cloud Pub/Sub for push notifications rather than native webhooks. Call `users.watch` with a Pub/Sub topic name; notifications deliver `historyId` values for incremental sync via `history.list`. Watch must be renewed every **7 days**. Rate limits use a quota unit system: 250 units/second per user, with `messages.get` costing 5 units.

**Content extraction**: Google Workspace documents can be exported via `files.export` to plain text, HTML, or PDF. Non-Google files (uploaded Word, PDF) must be downloaded as binary and parsed locally.

### Microsoft 365 (SharePoint, OneDrive)

All SharePoint and OneDrive access flows through **Microsoft Graph** using the same base URL as Teams. SharePoint uses a **Resource Unit (RU)** model for throttling rather than simple request counts.

**Key delta endpoint**: `GET /drives/{drive-id}/root/delta` provides efficient change tracking. The first call returns all items; subsequent calls with the stored `@odata.deltaLink` return only changes. Delta queries cost just **1 RU** (vs. 2 RU for regular list queries), making them the most efficient scanning method.

**Rate limits scale by tenant license count:**

| Licenses | RU/minute (per app) | RU/24 hours |
|---|---|---|
| 0–1,000 | 1,250 | 1,200,000 |
| 5,001–15,000 | 3,750 | 3,600,000 |
| 50,000+ | 6,250 | 6,000,000 |

**Webhooks** via Graph subscriptions support `driveItem` and `list` resources with a generous **30-day max subscription duration**. However, driveItem and list do **not** support rich notifications — you always receive basic notifications and must query Graph for full data.

**Document content extraction** is the biggest challenge. Graph provides no native text extraction for Word or PowerPoint — you must download the binary (`.docx`/`.pptx`) and parse locally using libraries like python-docx, Apache Tika, or the Open XML SDK. Excel is the exception: the Excel REST API provides structured JSON access to worksheets, ranges, and tables. SharePoint site pages can be read via `GET /sites/{id}/pages/{id}/microsoft.graph.sitePage?$expand=canvasLayout`, which returns structured HTML web part content.

---

## Dev and project tools: JIRA, Confluence, GitHub, Trello, Monday.com

### JIRA Cloud

**REST API v3** at `https://your-domain.atlassian.net/rest/api/3/` with JQL as the primary query language. The new search endpoint `POST /rest/api/3/search/jql` uses cursor-based pagination via `nextPageToken` (the legacy `/search` endpoint with `startAt`/`maxResults` is deprecated).

**Rate limits** as of March 2026 enforce **three independent systems simultaneously**: a points-based hourly quota (65,000 pts/hr on Tier 1, scaling to 500,000 pts/hr max on Tier 2), burst limits (**100 GET requests/second** per endpoint per tenant), and per-issue write limits. Each API response returns `X-RateLimit-Remaining` and `X-RateLimit-Reset` headers.

**Webhooks** support JQL-filtered subscriptions — you can register for `jira:issue_updated` only for `project = PROJ AND status = "In Progress"`. Dynamic webhooks via REST API expire after **30 days** and must be refreshed. Delivery is **best-effort, not guaranteed**, with max 20 concurrent requests per tenant + webhook URL host.

**Incremental sync** via JQL: `updated >= "-90d" ORDER BY updated ASC` with `nextPageToken` pagination. Expand `changelog` inline to get field change history without additional API calls.

### Confluence Cloud

**REST API v2** at `https://your-domain.atlassian.net/wiki/api/v2/` uses cursor-based pagination. Content body is available in multiple formats: `storage` (XHTML-like, best for processing), `atlas_doc_format` (ADF JSON), `view` (rendered HTML), and `export_view` (with macros resolved).

**CQL (Confluence Query Language)** enables incremental sync: `lastModified >= "2025-12-13" AND type=page`. Note that CQL index lag can be **several minutes** on Cloud — not suitable for real-time sync alone.

Webhooks cover page, blog, comment, attachment, space, and label events. Unlike JIRA, Confluence Cloud has **no native webhook admin UI** — registration requires the REST API or a Connect/Forge app.

### GitHub

GitHub offers both **REST API** (`https://api.github.com`, 5,000 requests/hour) and **GraphQL API** (`https://api.github.com/graphql`, 5,000 points/hour). The GraphQL API is particularly powerful for connectors — a single query can fetch PRs with reviews, comments, and author information, dramatically reducing API call volume.

**Webhooks** support 50+ event types with HMAC-SHA256 signature validation. The webhook delivery API (`GET /repos/{owner}/{repo}/hooks/{hook_id}/deliveries`) provides delivery history and redelivery capabilities, making it one of the most robust webhook implementations across all platforms.

**Polling fallback** uses conditional requests with `ETag`/`If-None-Match` headers — **304 responses don't count against rate limits**. The `since` parameter is available on commits, issues, and comments for date-based filtering. The Search API has a separate, stricter limit of **30 requests/minute**.

### Trello

**REST API** at `https://api.trello.com/1/` with authentication via API Key + Token (query parameters, not OAuth headers). Rate limits: **100 requests per 10 seconds per token**, **300 per 10 seconds per API key**.

Nested resources reduce API call volume significantly — a single request can return a board with all its lists, cards, members, and labels. The batch endpoint handles up to 10 URL requests in one call.

Webhooks are model-based (subscribe to a board, list, card, or member) and fire on all action types within that model. Signature validation uses HMAC-SHA1 (not SHA256). Webhooks are disabled after **30 days + 1,000 consecutive failures**.

### Monday.com

**GraphQL-only API** at `POST https://api.monday.com/v2` with a **complexity points system** instead of simple request counting. Each query is scored based on nesting depth and result volume. Limits: **10M complexity points/minute** for personal tokens, with daily call limits ranging from 200/day (Free) to 25,000/day (Enterprise).

Cursor-based pagination via `items_page` and `next_items_page` supports up to **500 items per page**. Activity logs provide date-filtered audit trails for polling fallback.

Webhooks are registered via GraphQL mutations and support events like `create_item`, `change_column_value`, `create_update`, and `item_deleted`. Verification uses a challenge-response handshake on creation.

---

## Systems of record: Salesforce and Workday

### Salesforce

Salesforce offers the richest real-time integration surface of any platform in scope. The **REST API** (current version v66.0) at `https://{MyDomain}.my.salesforce.com/services/data/v62.0/` provides SOQL queries, sObject CRUD, and the Composite API (batch up to 25 subrequests per call). **Bulk API 2.0** handles large data volumes asynchronously with no practical record limit per query job.

**Rate limits** are edition-based: Enterprise Edition gets **100,000 + 1,000/user license** API calls per 24-hour rolling window. Platform Events and CDC share a delivery budget of **50,000 external deliveries/day** (Unlimited Edition).

**Change Data Capture (CDC)** is the recommended real-time mechanism. It supports all custom objects plus key standard objects (Account, Contact, Opportunity, Lead, Case, Task, Event, User). CDC sends only changed fields with full operation metadata (CREATE, UPDATE, DELETE, UNDELETE), retains events for **72 hours** on the event bus, and supports replay. Subscribe via the **Pub/Sub API** (gRPC over HTTP/2 with Apache Avro binary format) — this is Salesforce's newest and most performant event interface.

**Polling fallback** via SOQL `WHERE LastModifiedDate > {timestamp}` returns up to 2,000 records per response with `queryMore`/`nextRecordsUrl` pagination (50,000 per transaction). The `/sobjects/{ObjectName}/updated/` endpoint returns just IDs of changed records within a timespan (max 30-day window), which is more efficient for detecting changes.

### Workday

Workday is the most constrained platform for external integration. The **SOAP Web Services (WWS)** API (v46.0) provides the most complete coverage — many operations (payroll, benefits, complex staffing) are SOAP-only. The REST API at `https://{domain}.workday.com/ccx/api/v1/{tenant}/` covers basic worker and organization queries but has limited functionality compared to SOAP.

**Report-as-a-Service (RaaS)** exposes custom reports as REST endpoints and is often the most practical approach for custom data extracts: `GET /ccx/service/customreport2/{tenant}/{owner}/{report}?format=json`.

**Workday does not natively support real-time webhooks for external consumers.** Polling is the standard approach. Rate limits are **not publicly documented** — community-reported throughput is approximately **10 requests/second**, with SOAP requests often taking ~90 seconds regardless of record count due to XML processing overhead. SOAP pagination defaults to 100 records/page (max 999).

**Incremental sync** uses the `Updated_From`/`Updated_Through` parameters in SOAP requests, or date-prompted RaaS reports. A critical consideration: Workday's data model is heavily **effective-dated**, meaning a record modified today could have a retroactive effective date — periodic full reconciliation is necessary to catch these.

**Authentication** uses OAuth 2.0 with an Integration System User (ISU) — a dedicated service account assigned to Integration System Security Groups with specific domain permissions.

---

## A unified data model for the knowledge graph

The core challenge is representing entities from 12 different platforms in a single, queryable schema with cross-platform identity resolution. The recommended approach uses **email as the primary key** for Person nodes, with a separate `platform_identities` table linking each Person to their platform-specific IDs (Slack `U0123ABC`, GitHub `johndoe`, JIRA `accountId`, Salesforce `005...`).

### PostgreSQL schema with pgvector (recommended primary store)

```sql
CREATE TABLE persons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_email TEXT UNIQUE NOT NULL,
    display_name TEXT,
    embedding vector(1536),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE platform_identities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID REFERENCES persons(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    platform_user_id TEXT NOT NULL,
    platform_username TEXT,
    profile_url TEXT,
    raw_profile JSONB,
    UNIQUE(platform, platform_user_id)
);

CREATE TABLE entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type TEXT NOT NULL,  -- Document, Message, Task, Project, Channel, etc.
    platform TEXT NOT NULL,
    platform_entity_id TEXT NOT NULL,
    title TEXT,
    content TEXT,
    content_embedding vector(1536),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    synced_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,  -- 3-month rolling window
    UNIQUE(platform, platform_entity_id)
);

CREATE TABLE edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    edge_type TEXT NOT NULL,  -- authored, mentioned_in, assigned_to, etc.
    source_entity_id UUID REFERENCES entities(id),
    source_person_id UUID REFERENCES persons(id),
    target_entity_id UUID REFERENCES entities(id),
    target_person_id UUID REFERENCES persons(id),
    platform TEXT,
    properties JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for hybrid search
CREATE INDEX idx_entities_embedding ON entities
    USING ivfflat (content_embedding vector_cosine_ops);
CREATE INDEX idx_entities_fulltext ON entities
    USING gin(to_tsvector('english', coalesce(title,'') || ' ' || coalesce(content,'')));
CREATE INDEX idx_entities_type ON entities(entity_type);
CREATE INDEX idx_entities_expires ON entities(expires_at);
```

The `UNIQUE(platform, platform_entity_id)` constraint on `entities` serves double duty: it prevents duplicates and enables efficient upserts via `ON CONFLICT DO UPDATE`. The `expires_at` column implements the 3-month rolling window — a scheduled `pg_cron` job deletes expired rows daily.

### Neo4j overlay for graph traversal

For multi-hop relationship queries (finding all context connected to a person across platforms), Neo4j provides dramatically better query ergonomics than recursive SQL CTEs:

```cypher
MATCH (p:Person {email: $email})-[r*1..3]-(connected)
WHERE connected.expires_at > datetime()
RETURN p, r, connected
ORDER BY connected.updated_at DESC LIMIT 50
```

The recommended architecture uses PostgreSQL as the primary store (entities, vectors, full-text) with Neo4j as an optional graph overlay for relationship-heavy queries. Writes go to PostgreSQL first, then sync to Neo4j asynchronously.

### Entity type mapping across platforms

| Unified Type | Slack | Teams | Google | M365/SP | JIRA | Confluence | GitHub | Trello | Monday | Salesforce | Workday |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Person** | user | user | user | user | user | user | user | member | user | User/Contact | Worker |
| **Message** | message | chatMessage | — | — | comment | comment | issue_comment | action(comment) | update | — | — |
| **Document** | canvas | — | Doc/Sheet | docx/xlsx | — | page | — | — | doc | — | — |
| **Task** | — | — | — | — | issue | — | issue/PR | card | item | Task | inbox_task |
| **Project** | — | team | — | site | project | space | repository | board | board | Opportunity | — |
| **Channel** | channel | channel | — | — | — | — | discussion | list | group | — | — |
| **File** | file | driveItem | file | driveItem | attachment | attachment | blob | attachment | asset | ContentDocument | — |

---

## Connector architecture for real-time sync

### Three-phase sync design

The sync agent operates in three modes simultaneously:

**Phase 1 — Observation-triggered fetch.** When the user dwells on a resource (focus event > N seconds without departure), the agent fetches it and related context via API. Use platform-specific endpoints optimized for low-latency retrieval: Slack `conversations.history`, JIRA `/issue/{key}`, GitHub GraphQL for PRs, Google Docs API. Each fetch is rate-limited with a token bucket algorithm per platform.

**Phase 2 — Real-time webhook/event stream.** Webhook receivers for platforms with strong event support: Slack Events API (Socket Mode for local), GitHub webhooks, JIRA webhooks, Salesforce CDC via Pub/Sub API, Google Drive `changes.watch`, and Microsoft Graph subscriptions. The receiver acknowledges within 200ms, enqueues the event in Redis/SQS, and a worker processes it asynchronously.

**Phase 3 — Periodic reconciliation.** Scheduled jobs every 6–12 hours compare local state against source APIs using delta endpoints (Drive `changes.list`, Graph `delta`, JIRA JQL with `updated >=`). This catches webhook delivery failures, subscription expirations, and data that slipped through gaps.

### Webhook ingestion for local development

For a system running on a local machine, webhooks require a tunnel:

- **Cloudflare Tunnel** (free, `cloudflared tunnel`): Stable, production-grade, recommended
- **ngrok** (free tier available): Quick setup, but URLs change on restart unless paid
- **Tailscale Funnel**: Good for development, zero-config networking

The webhook receiver should verify signatures (HMAC-SHA256 for GitHub/Slack, certificate validation for Microsoft Graph rich notifications), generate an idempotency key (`{platform}:{entity_type}:{platform_entity_id}`), dedup against a Redis SET with TTL, and enqueue for async processing.

### Rate limit management

Each platform connector maintains its own token bucket with platform-specific parameters. A priority queue ensures webhook-triggered fetches (priority 0) get tokens before reconciliation jobs (priority 1) and backfill tasks (priority 2). Always honor `Retry-After` headers. Implement circuit breakers that open after >50% error rate in a 60-second window.

### Subscription lifecycle management

Several platforms require active subscription renewal:

- Google Drive `changes.watch`: **7-day max**, renew before expiry
- Gmail `users.watch`: **7-day max**, recommend daily renewal
- Microsoft Graph subscriptions: **30 days** for driveItem/list, **60 minutes** for Teams messages without lifecycle URL
- JIRA dynamic webhooks: **30-day expiry**, refresh via `PUT /rest/api/3/webhook/refresh`

A dedicated scheduler must track all active subscriptions and renew them proactively, with alerting on renewal failures.

---

## Existing open-source frameworks and how they fit

**Nango** is the strongest recommendation for the auth and sync infrastructure layer. It supports all 12 target platforms, handles OAuth token refresh, rate limiting, pagination, and webhook reception natively. You write TypeScript sync functions that extract entities and push to your graph database. Nango handles the plumbing — it is production-tested by Replit and Ramp.

**Cost:** Free open-source (self-hosted). Nango Cloud available (starting $250/month for managed hosting + support).

**Airbyte** excels at batch backfill with 600+ connectors including all target platforms. Its newer **Agent Connectors** provide standalone Python SDKs optimized for AI agent use cases (GitHub, JIRA, Salesforce). Use PyAirbyte for initial data loading, then Nango for ongoing real-time sync.

**Cost:** Free open-source (self-hosted). Airbyte Cloud starts at $2.50/credit (1M rows ≈ 6-8 credits). For 12 platforms with 3-month backfill across a medium org, expect ~$150-300 one-time, then minimal ongoing costs with delta sync.

**Unstructured.io** fills the document processing gap. It has source connectors for Confluence, Google Drive, SharePoint, Slack, and JIRA, with intelligent partitioning, chunking, and metadata extraction from unstructured content (PDFs, Word docs, HTML pages). Use it specifically for processing Document/File node content before embedding.

**Cost:** Free open-source library (self-hosted processing). Unstructured API/Platform available (starting $99/month for hosted API with higher throughput).

**LlamaIndex** and **LangChain** provide document loaders for most target platforms, but these are designed for one-shot RAG ingestion, not continuous sync. They lack webhook support, deduplication, and incremental update logic. Their value lies downstream: LangChain's `LLMGraphTransformer` can auto-extract entities and relationships from document content into Neo4j, and LlamaIndex's `PropertyGraphIndex` can build graph structures from loaded documents.

**Cost:** Free open-source libraries. No licensing costs for self-hosted use.

**MCP servers** (Model Context Protocol) should be the **query interface**, not the sync mechanism. Existing community servers cover Slack (korotovsky/slack-mcp-server), JIRA/Confluence (sooperset/mcp-atlassian), and GitHub. However, these make real-time API calls per request — they don't maintain a local graph. The recommended pattern: build the persistent knowledge graph via the connector architecture, then expose it through custom MCP tools that query the local graph.

**Cost:** Free open-source protocol and community servers.

**Notable mentions**: Cognee (open-source memory engine that builds knowledge graphs with hybrid vector+graph search), CocoIndex (incremental processing framework for Neo4j knowledge graphs with LLM-based entity extraction), and Composio (250+ tool integrations, MCP-compatible, designed for AI agent actions).

**Cost:** All free open-source. Cognee and CocoIndex are fully self-hosted. Composio offers a hosted version (free tier available, pro plans from $29/month).

---

## How an AI agent interacts with the knowledge graph

### The coding agent analogy

Claude Code interacts with a codebase through a small set of primitives: `file_tree` (directory listing), `grep` (search), `read_file` (detailed content), and navigation along imports/references. The knowledge graph analog maps directly:

| Coding Agent | Knowledge Graph Agent |
|---|---|
| `file_tree` — browse directory structure | `list_sources()` — show connected platforms, entity counts, org structure |
| `grep` — search for text patterns | `search(query)` — hybrid semantic + full-text search across all entities |
| `read_file` — get specific file content | `get_entity(id)` — fetch full context for a message, document, or task |
| Follow imports/references | `traverse(entity_id, depth=2)` — follow relationships 1–2 hops |
| Understand project structure | `get_project_context(name)` — all tasks, docs, messages, people for a project |

**The key insight**: just as a coding agent uses `grep` to cast a wide net and `read_file` to drill down, a knowledge graph agent uses **semantic search** to find starting nodes and **graph traversal** to gather rich context around them.

### Recommended MCP tools

```python
@mcp.tool()
def search_entities(query: str, types: list = None, limit: int = 10):
    """Hybrid semantic + full-text search across all platforms."""

@mcp.tool()
def get_person_context(email: str):
    """Full cross-platform context: tasks, messages, docs, meetings."""

@mcp.tool()
def get_project_status(project_name: str):
    """Tasks by status, recent messages, key docs, team, blockers."""

@mcp.tool()
def find_related_documents(query: str, limit: int = 10):
    """Semantic search for documents and files with graph context."""

@mcp.tool()
def get_recent_messages(channel: str = None, person: str = None, hours: int = 24):
    """Recent messages with thread context and sender info."""

@mcp.tool()
def find_experts(topic: str, limit: int = 5):
    """People most connected to a topic via authored docs, tasks, reviews."""
```

### Hybrid retrieval architecture

The most effective query strategy combines three methods using **Reciprocal Rank Fusion (RRF)**:

1. **Vector similarity** via pgvector — captures semantic meaning ("who is working on the billing migration?" finds relevant content even without exact keyword matches)
2. **Full-text search** via PostgreSQL `tsvector` — captures exact terminology (project names, JIRA keys, technical terms)
3. **Graph traversal** via Neo4j Cypher or recursive SQL — captures structural relationships (Person → authored → Document → belongs_to → Project → has_task → Task → assigned_to → Person)

The agent first retrieves candidate entities via search, then enriches them with 1–2 hops of graph context before packing into the context window. For large result sets, an LLM summarization pass compresses context (e.g., "John has 12 open tasks in Project X, was most active in #engineering with 47 messages this week").

---

## Conclusion: what makes this architecture distinctive

The system described here differs from existing solutions in three important ways. First, it maintains a **persistent, structured local graph** rather than making real-time API calls per query — this means AI agent queries are fast, offline-capable, and don't consume API quotas at query time. Second, the **cross-platform identity resolution** layer (email-keyed Person nodes with platform identity links) transforms siloed data into a connected graph where traversing from a Slack message to a JIRA ticket to a GitHub PR to a Salesforce opportunity follows explicit relationship edges. Third, the **hybrid retrieval** combining vectors, full-text, and graph traversal provides query capabilities that none of these mechanisms can achieve alone.

The hardest engineering challenge is not any single connector but the **ongoing subscription lifecycle management** across 12 platforms with different expiration policies, webhook delivery guarantees, and failure modes. Nango handles much of this complexity, but the reconciliation layer — detecting and backfilling missed events — must be custom-built with platform-specific delta query logic.

For a practical starting point, build the PostgreSQL schema first (it handles entities, vectors, full-text, and relationships in a single database), connect Slack and GitHub (they have the best webhook support and most generous rate limits), implement the three-phase sync, and expose the graph via MCP tools. Workday should be last — its polling-only model, undocumented rate limits, and SOAP-heavy API make it the highest-effort integration per unit of value.