import { useState } from "react";

const COLORS = {
  bg: "#0d0f14",
  surface: "#141720",
  surfaceHover: "#1a1f2e",
  border: "#242938",
  borderBright: "#2e3650",
  accent: "#e8a045",
  accentDim: "#a06820",
  green: "#4ade80",
  blue: "#60a5fa",
  purple: "#a78bfa",
  pink: "#f472b6",
  red: "#f87171",
  cyan: "#22d3ee",
  text: "#e2e8f0",
  textMuted: "#64748b",
  textDim: "#94a3b8",
};

const ENTITY_COLORS = {
  Person: COLORS.green,
  Message: COLORS.blue,
  Channel: COLORS.purple,
  File: COLORS.pink,
  Task: COLORS.accent,
  Document: COLORS.cyan,
};

const EDGE_COLORS = {
  authored: COLORS.green,
  posted_in: COLORS.purple,
  replies_to: COLORS.blue,
  mentioned_in: COLORS.pink,
  reacted_to: COLORS.accent,
  references: COLORS.cyan,
  assigned_to: COLORS.red,
  linked_from: COLORS.cyan,
};

// ─── shared components ────────────────────────────────────────────────────────

function Tag({ color, children, size = "sm" }) {
  return (
    <span style={{
      background: color + "22",
      border: `1px solid ${color}55`,
      color,
      borderRadius: 4,
      padding: size === "xs" ? "1px 5px" : "2px 8px",
      fontSize: size === "xs" ? 10 : 11,
      fontFamily: "monospace",
      fontWeight: 600,
      whiteSpace: "nowrap",
      letterSpacing: "0.02em",
    }}>
      {children}
    </span>
  );
}

function Code({ children, block }) {
  const style = block ? {
    display: "block",
    background: "#080a0f",
    border: `1px solid ${COLORS.border}`,
    borderRadius: 6,
    padding: "12px 14px",
    fontFamily: "monospace",
    fontSize: 12,
    color: COLORS.textDim,
    lineHeight: 1.7,
    overflowX: "auto",
    whiteSpace: "pre",
  } : {
    fontFamily: "monospace",
    fontSize: 12,
    color: COLORS.cyan,
    background: "#080a0f",
    padding: "1px 5px",
    borderRadius: 3,
  };
  return <code style={style}>{children}</code>;
}

function Section({ title, children, accent }) {
  return (
    <div style={{ marginBottom: 28 }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 10, marginBottom: 14,
        borderBottom: `1px solid ${COLORS.border}`, paddingBottom: 10,
      }}>
        <div style={{ width: 3, height: 16, background: accent || COLORS.accent, borderRadius: 2 }} />
        <span style={{ color: COLORS.text, fontWeight: 700, fontSize: 13, letterSpacing: "0.06em", textTransform: "uppercase" }}>{title}</span>
      </div>
      {children}
    </div>
  );
}

function Table({ cols, rows }) {
  return (
    <div style={{ overflowX: "auto", borderRadius: 8, border: `1px solid ${COLORS.border}` }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, fontFamily: "monospace" }}>
        <thead>
          <tr style={{ background: "#0a0c11" }}>
            {cols.map((c, i) => (
              <th key={i} style={{
                padding: "8px 14px", textAlign: "left",
                color: COLORS.textMuted, fontWeight: 600,
                borderBottom: `1px solid ${COLORS.border}`,
                whiteSpace: "nowrap", letterSpacing: "0.04em", fontSize: 11,
              }}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri} style={{ borderBottom: `1px solid ${COLORS.border}88`, transition: "background 0.15s" }}
              onMouseEnter={e => e.currentTarget.style.background = COLORS.surfaceHover}
              onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
              {row.map((cell, ci) => (
                <td key={ci} style={{ padding: "7px 14px", color: COLORS.textDim, verticalAlign: "top" }}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── TAB 1: Schema ER Diagram ─────────────────────────────────────────────────

function SchemaView() {
  const tables = [
    {
      name: "persons",
      color: COLORS.green,
      x: 20, y: 80,
      fields: [
        ["id", "UUID PK"],
        ["canonical_email", "TEXT UNIQUE"],
        ["display_name", "TEXT"],
        ["embedding", "vector(1536)"],
        ["created_at", "TIMESTAMPTZ"],
      ]
    },
    {
      name: "platform_identities",
      color: COLORS.cyan,
      x: 20, y: 320,
      fields: [
        ["id", "UUID PK"],
        ["person_id", "UUID FK→persons"],
        ["platform", "TEXT"],
        ["platform_user_id", "TEXT"],
        ["platform_username", "TEXT"],
        ["raw_profile", "JSONB"],
      ]
    },
    {
      name: "entities",
      color: COLORS.blue,
      x: 400, y: 40,
      fields: [
        ["id", "UUID PK"],
        ["entity_type", "TEXT"],
        ["platform", "TEXT"],
        ["platform_entity_id", "TEXT UNIQUE"],
        ["title", "TEXT"],
        ["content", "TEXT"],
        ["content_embedding", "vector(1536)"],
        ["metadata", "JSONB"],
        ["created_at", "TIMESTAMPTZ"],
        ["updated_at", "TIMESTAMPTZ"],
        ["expires_at", "TIMESTAMPTZ"],
      ]
    },
    {
      name: "edges",
      color: COLORS.accent,
      x: 400, y: 400,
      fields: [
        ["id", "UUID PK"],
        ["edge_type", "TEXT"],
        ["source_entity_id", "UUID FK→entities"],
        ["source_person_id", "UUID FK→persons"],
        ["target_entity_id", "UUID FK→entities"],
        ["target_person_id", "UUID FK→persons"],
        ["platform", "TEXT"],
        ["properties", "JSONB"],
        ["created_at", "TIMESTAMPTZ"],
      ]
    },
  ];

  const rowH = 22, headerH = 36, pad = 14;
  const tableWidth = 260;

  const getTableHeight = (t) => headerH + t.fields.length * rowH + pad;
  const getTableCenter = (t) => ({
    x: t.x + tableWidth / 2,
    y: t.y + getTableHeight(t) / 2,
  });

  const connections = [
    { from: "persons", fromEdge: "right", to: "platform_identities", toEdge: "left", label: "1:N", color: COLORS.cyan },
    { from: "persons", fromEdge: "right", to: "edges", toEdge: "left", label: "authored", color: COLORS.accent },
    { from: "entities", fromEdge: "bottom", to: "edges", toEdge: "top", label: "source/target", color: COLORS.accent },
  ];

  return (
    <div>
      <p style={{ color: COLORS.textDim, fontSize: 13, marginBottom: 20, lineHeight: 1.7 }}>
        Four tables form the complete schema. <Tag color={COLORS.green}>persons</Tag> are canonical identities resolved across all platforms.{" "}
        <Tag color={COLORS.blue}>entities</Tag> hold every message, document, task, and file — all platforms, all types.{" "}
        <Tag color={COLORS.accent}>edges</Tag> are the relationships between them. <Tag color={COLORS.cyan}>platform_identities</Tag> maps one person to many platform-specific IDs.
      </p>
      <div style={{ overflowX: "auto" }}>
        <svg width={720} height={580} style={{ fontFamily: "monospace", display: "block" }}>
          {/* Connection lines */}
          {/* persons → platform_identities */}
          <line x1={20 + tableWidth} y1={320 + 24} x2={20 + tableWidth} y2={320 + 24} />

          {/* persons to platform_identities */}
          <path d={`M ${20 + tableWidth} ${230} L ${20 + tableWidth + 30} ${230} L ${20 + tableWidth + 30} ${320} L ${20 + tableWidth} ${320}`}
            stroke={COLORS.cyan} strokeWidth={1.5} fill="none" strokeDasharray="4,3" opacity={0.7} />
          <text x={20 + tableWidth + 35} y={278} fontSize={10} fill={COLORS.cyan} opacity={0.9}>1:N</text>

          {/* persons to edges */}
          <path d={`M ${20 + tableWidth} ${160} Q ${340} ${160} ${400} ${450}`}
            stroke={COLORS.accent} strokeWidth={1.5} fill="none" strokeDasharray="4,3" opacity={0.7} />
          <text x={240} y={340} fontSize={10} fill={COLORS.accent} opacity={0.9}>source_person_id</text>

          {/* entities to edges */}
          <path d={`M ${400 + tableWidth / 2} ${40 + getTableHeight(tables[2])} L ${400 + tableWidth / 2} ${400}`}
            stroke={COLORS.accent} strokeWidth={1.5} fill="none" strokeDasharray="4,3" opacity={0.7} />
          <text x={415} y={390} fontSize={10} fill={COLORS.accent} opacity={0.9}>source/target_entity_id</text>

          {/* Tables */}
          {tables.map((t) => {
            const h = getTableHeight(t);
            return (
              <g key={t.name}>
                {/* Shadow */}
                <rect x={t.x + 4} y={t.y + 4} width={tableWidth} height={h} rx={6} fill="black" opacity={0.4} />
                {/* Body */}
                <rect x={t.x} y={t.y} width={tableWidth} height={h} rx={6}
                  fill={COLORS.surface} stroke={t.color} strokeWidth={1.5} strokeOpacity={0.6} />
                {/* Header */}
                <rect x={t.x} y={t.y} width={tableWidth} height={headerH} rx={6} fill={t.color + "22"} />
                <rect x={t.x} y={t.y + headerH - 6} width={tableWidth} height={6} fill={t.color + "22"} />
                {/* Header text */}
                <text x={t.x + 12} y={t.y + 23} fontSize={13} fontWeight={700} fill={t.color}>{t.name}</text>
                {/* Fields */}
                {t.fields.map(([name, type], fi) => (
                  <g key={name}>
                    <line x1={t.x} y1={t.y + headerH + fi * rowH} x2={t.x + tableWidth}
                      y2={t.y + headerH + fi * rowH} stroke={COLORS.border} strokeWidth={1} />
                    <text x={t.x + 12} y={t.y + headerH + fi * rowH + 15} fontSize={11} fill={COLORS.textDim}>{name}</text>
                    <text x={t.x + tableWidth - 10} y={t.y + headerH + fi * rowH + 15} fontSize={10}
                      fill={type.includes("FK") ? COLORS.accent + "cc" : COLORS.textMuted}
                      textAnchor="end">{type}</text>
                  </g>
                ))}
              </g>
            );
          })}
        </svg>
      </div>

      <div style={{ marginTop: 20, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div style={{ background: COLORS.surface, border: `1px solid ${COLORS.border}`, borderRadius: 8, padding: 14 }}>
          <div style={{ color: COLORS.accent, fontWeight: 700, fontSize: 12, marginBottom: 8 }}>KEY DESIGN DECISIONS</div>
          <ul style={{ color: COLORS.textDim, fontSize: 12, lineHeight: 1.8, margin: 0, paddingLeft: 16 }}>
            <li><Code>canonical_email</Code> is the cross-platform identity anchor</li>
            <li><Code>entities</Code> is a single table for ALL platforms and types</li>
            <li><Code>content_embedding</Code> enables semantic search on every entity</li>
            <li><Code>expires_at</Code> implements the 3-month rolling window natively</li>
            <li><Code>metadata JSONB</Code> stores platform-specific fields without schema sprawl</li>
          </ul>
        </div>
        <div style={{ background: COLORS.surface, border: `1px solid ${COLORS.border}`, borderRadius: 8, padding: 14 }}>
          <div style={{ color: COLORS.blue, fontWeight: 700, fontSize: 12, marginBottom: 8 }}>ENTITY TYPES (entity_type column)</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {["Message", "Channel", "Document", "Task", "File", "Project", "Event", "Comment", "Review", "Repository"].map(t => (
              <Tag key={t} color={ENTITY_COLORS[t] || COLORS.textDim} size="xs">{t}</Tag>
            ))}
          </div>
          <div style={{ color: COLORS.blue, fontWeight: 700, fontSize: 12, marginBottom: 8, marginTop: 12 }}>EDGE TYPES (edge_type column)</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {["authored", "posted_in", "replies_to", "mentioned_in", "reacted_to", "references", "assigned_to", "linked_from", "belongs_to"].map(t => (
              <Tag key={t} color={EDGE_COLORS[t] || COLORS.textDim} size="xs">{t}</Tag>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── TAB 2: Slack → Graph Mapping ─────────────────────────────────────────────

const slackThread = {
  channel: { id: "C04BILLING", name: "billing-migration", topic: "Q1 billing system migration" },
  messages: [
    {
      ts: "1742956800.001",
      user: { id: "U0SARAH", name: "sarah.chen", email: "sarah.chen@acme.com" },
      text: "Hey @james, I just pushed a fix for the duplicate charge bug. PR is up: https://github.com/acme/billing/pull/482\nCan you also check JIRA-1203? The Salesforce sync is still broken.",
      reactions: [{ emoji: "👍", user: "U0JAMES" }, { emoji: "🔥", user: "U0PRIYA" }],
      files: [],
      replies: [
        {
          ts: "1742957100.002",
          user: { id: "U0JAMES", name: "james.wright", email: "james.wright@acme.com" },
          text: "On it. I can see the Salesforce issue — it's the OAuth token refresh failing silently. I'll add this to the sync-failures doc.",
          files: [],
        },
        {
          ts: "1742957400.003",
          user: { id: "U0PRIYA", name: "priya.patel", email: "priya.patel@acme.com" },
          text: "The billing migration was supposed to be done by EOW @sarah. Are we still on track?",
          files: [],
        },
        {
          ts: "1742957700.004",
          user: { id: "U0SARAH", name: "sarah.chen", email: "sarah.chen@acme.com" },
          text: "The PR should unblock it. Once James reviews and CI passes we should be fine.",
          files: [],
        }
      ]
    }
  ]
};

function SlackMessage({ msg, isReply }) {
  return (
    <div style={{
      display: "flex", gap: 10, padding: isReply ? "6px 12px 6px 40px" : "10px 12px",
      borderLeft: isReply ? `2px solid ${COLORS.border}` : "none",
      marginLeft: isReply ? 16 : 0,
    }}>
      <div style={{
        width: 32, height: 32, borderRadius: 6, flexShrink: 0,
        background: `hsl(${msg.user.id.charCodeAt(2) * 40}deg 50% 35%)`,
        display: "flex", alignItems: "center", justifyContent: "center",
        color: "white", fontSize: 13, fontWeight: 700,
      }}>{msg.user.name[0].toUpperCase()}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "baseline", marginBottom: 3 }}>
          <span style={{ color: COLORS.text, fontWeight: 700, fontSize: 13 }}>{msg.user.name}</span>
          <span style={{ color: COLORS.textMuted, fontSize: 11 }}>{new Date(parseFloat(msg.ts) * 1000).toLocaleTimeString()}</span>
        </div>
        <div style={{ color: COLORS.textDim, fontSize: 13, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>
          {msg.text.split(/(https?:\/\/\S+|@\w+|JIRA-\d+)/g).map((part, i) => {
            if (part.startsWith("http")) return <span key={i} style={{ color: COLORS.blue, textDecoration: "underline", cursor: "pointer" }}>{part}</span>;
            if (part.startsWith("@")) return <span key={i} style={{ color: COLORS.cyan, background: COLORS.cyan + "15", borderRadius: 3, padding: "0 2px" }}>{part}</span>;
            if (part.match(/JIRA-\d+/)) return <span key={i} style={{ color: COLORS.accent, background: COLORS.accent + "15", borderRadius: 3, padding: "0 2px" }}>{part}</span>;
            return part;
          })}
        </div>
        {msg.reactions && msg.reactions.length > 0 && (
          <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
            {msg.reactions.map((r, i) => (
              <span key={i} style={{
                background: COLORS.border, borderRadius: 12, padding: "2px 8px",
                fontSize: 12, color: COLORS.textDim,
              }}>{r.emoji} 1</span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function MappingView() {
  const [activeMsg, setActiveMsg] = useState(null);

  const msg = slackThread.messages[0];

  const entitiesData = [
    ["channel-C04BILLING", "Channel", "slack", "C04BILLING", "#billing-migration", '{"topic":"Q1 billing system migration"}', "—"],
    ["msg-1742956800.001", "Message", "slack", "1742956800.001", null, '{"ts":"1742956800.001","thread_ts":null,"has_replies":true}', "2025-04-17 11:20:00"],
    ["msg-1742957100.002", "Message", "slack", "1742957100.002", null, '{"thread_ts":"1742956800.001","parent_id":"msg-...001"}', "2025-04-17 11:25:00"],
    ["msg-1742957400.003", "Message", "slack", "1742957400.003", null, '{"thread_ts":"1742956800.001","parent_id":"msg-...001"}', "2025-04-17 11:30:00"],
    ["msg-1742957700.004", "Message", "slack", "1742957700.004", null, '{"thread_ts":"1742956800.001","parent_id":"msg-...001"}', "2025-04-17 11:35:00"],
  ];

  const personsData = [
    ["sarah.chen@acme.com", "Sarah Chen"],
    ["james.wright@acme.com", "James Wright"],
    ["priya.patel@acme.com", "Priya Patel"],
  ];

  const platformIds = [
    ["sarah.chen@...", "slack", "U0SARAH", "sarah.chen"],
    ["james.wright@...", "slack", "U0JAMES", "james.wright"],
    ["priya.patel@...", "slack", "U0PRIYA", "priya.patel"],
  ];

  const edgesData = [
    ["authored", "person:sarah.chen@...", "entity:msg-...001", "sarah.chen@acme.com wrote message 001"],
    ["posted_in", "entity:msg-...001", "entity:channel-C04BILLING", "message posted in #billing-migration"],
    ["replies_to", "entity:msg-...002", "entity:msg-...001", "james replied to sarah's message"],
    ["replies_to", "entity:msg-...003", "entity:msg-...001", "priya replied to sarah's message"],
    ["replies_to", "entity:msg-...004", "entity:msg-...001", "sarah replied again"],
    ["mentioned_in", "person:james.wright@...", "entity:msg-...001", "@james mentioned in root message"],
    ["authored", "person:james.wright@...", "entity:msg-...002", "james wrote reply 002"],
    ["authored", "person:priya.patel@...", "entity:msg-...003", "priya wrote reply 003"],
    ["authored", "person:sarah.chen@...", "entity:msg-...004", "sarah wrote reply 004"],
    ["mentioned_in", "person:sarah.chen@...", "entity:msg-...003", "@sarah mentioned in priya's reply"],
    ["reacted_to", "person:james.wright@...", "entity:msg-...001", "👍 reaction"],
    ["reacted_to", "person:priya.patel@...", "entity:msg-...001", "🔥 reaction"],
    ["references", "entity:msg-...001", "entity:github-pr-482", "URL to GitHub PR #482 extracted"],
    ["references", "entity:msg-...001", "entity:jira-JIRA-1203", "JIRA-1203 mentioned → linked"],
    ["references", "entity:msg-...002", "entity:doc-sync-failures", "'sync-failures doc' name-matched"],
  ];

  return (
    <div>
      <p style={{ color: COLORS.textDim, fontSize: 13, marginBottom: 20, lineHeight: 1.7 }}>
        This is the source Slack thread on the left. Every element — messages, users, reactions, URL references — gets parsed into rows in the schema. Hover over a row to see what it represents.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 24 }}>
        {/* Slack thread */}
        <div>
          <div style={{ color: COLORS.textMuted, fontWeight: 700, fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 10 }}>SOURCE: Slack Thread</div>
          <div style={{ background: "#1a1d27", border: `1px solid ${COLORS.border}`, borderRadius: 8, overflow: "hidden" }}>
            <div style={{ background: "#13151f", padding: "8px 14px", borderBottom: `1px solid ${COLORS.border}`, display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ color: COLORS.purple, fontWeight: 700, fontSize: 13 }}>#billing-migration</span>
              <span style={{ color: COLORS.textMuted, fontSize: 11 }}>Q1 billing system migration</span>
            </div>
            <div style={{ padding: "4px 0" }}>
              <SlackMessage msg={msg} isReply={false} />
              <div style={{ padding: "2px 12px 4px", borderLeft: `2px solid ${COLORS.border}`, marginLeft: 16 }}>
                <span style={{ color: COLORS.textMuted, fontSize: 11 }}>3 replies in thread ↓</span>
              </div>
              {msg.replies.map((r, i) => <SlackMessage key={i} msg={r} isReply={true} />)}
            </div>
          </div>
        </div>

        {/* What gets extracted */}
        <div>
          <div style={{ color: COLORS.textMuted, fontWeight: 700, fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 10 }}>EXTRACTED REFERENCES</div>
          <div style={{ background: COLORS.surface, border: `1px solid ${COLORS.border}`, borderRadius: 8, padding: 14, display: "flex", flexDirection: "column", gap: 10 }}>
            {[
              { label: "4 entities: 4 × Message", color: COLORS.blue, detail: "root + 3 thread replies" },
              { label: "1 entity: Channel", color: COLORS.purple, detail: "#billing-migration" },
              { label: "3 persons resolved", color: COLORS.green, detail: "Sarah, James, Priya (by email from profile)" },
              { label: "2 reactions → 2 edges", color: COLORS.accent, detail: "reacted_to edges" },
              { label: "URL → GitHub PR #482", color: COLORS.cyan, detail: "references edge to GitHub entity" },
              { label: "JIRA-1203 mention", color: COLORS.accent, detail: "references edge to JIRA entity" },
              { label: "'sync-failures doc'", color: COLORS.pink, detail: "fuzzy-matched to Confluence doc → references edge" },
              { label: "@mentions → 2 edges", color: COLORS.green, detail: "mentioned_in edges for @james, @sarah" },
            ].map((item, i) => (
              <div key={i} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                <div style={{ width: 6, height: 6, borderRadius: "50%", background: item.color, marginTop: 5, flexShrink: 0 }} />
                <div>
                  <span style={{ color: item.color, fontFamily: "monospace", fontSize: 12, fontWeight: 600 }}>{item.label}</span>
                  <span style={{ color: COLORS.textMuted, fontSize: 11, marginLeft: 8 }}>{item.detail}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <Section title="persons table — 3 rows" accent={COLORS.green}>
        <Table
          cols={["canonical_email", "display_name"]}
          rows={personsData.map(([email, name]) => [
            <Code>{email}</Code>,
            <span style={{ color: COLORS.text }}>{name}</span>,
          ])}
        />
      </Section>

      <Section title="platform_identities table — 3 rows (Slack only; more added for GitHub, JIRA etc.)" accent={COLORS.cyan}>
        <Table
          cols={["person_id (→email)", "platform", "platform_user_id", "platform_username"]}
          rows={platformIds.map(([p, pl, id, un]) => [
            <Code>{p}</Code>,
            <Tag color={COLORS.cyan} size="xs">{pl}</Tag>,
            <Code>{id}</Code>,
            <span style={{ color: COLORS.textDim }}>{un}</span>,
          ])}
        />
      </Section>

      <Section title="entities table — 5 rows from this thread" accent={COLORS.blue}>
        <Table
          cols={["id (abbreviated)", "entity_type", "platform", "platform_entity_id", "title", "metadata", "expires_at"]}
          rows={entitiesData.map(([id, type, pl, eid, title, meta, exp]) => [
            <Code>{id}</Code>,
            <Tag color={ENTITY_COLORS[type]} size="xs">{type}</Tag>,
            <Tag color={COLORS.cyan} size="xs">{pl}</Tag>,
            <Code>{eid}</Code>,
            title ? <span style={{ color: COLORS.textDim }}>{title}</span> : <span style={{ color: COLORS.textMuted }}>—</span>,
            <span style={{ color: COLORS.textMuted, fontFamily: "monospace", fontSize: 10 }}>{meta}</span>,
            exp === "—" ? <span style={{ color: COLORS.textMuted }}>—</span> : <Code>{exp}</Code>,
          ])}
        />
        <p style={{ color: COLORS.textMuted, fontSize: 11, marginTop: 8 }}>
          Note: the <Code>content</Code> column (not shown) stores the full message text. <Code>content_embedding</Code> is a 1536-dim vector generated by running the content through an embedding model.
        </p>
      </Section>

      <Section title={`edges table — ${edgesData.length} rows from this thread`} accent={COLORS.accent}>
        <Table
          cols={["edge_type", "source", "target", "meaning"]}
          rows={edgesData.map(([type, src, tgt, meaning]) => [
            <Tag color={EDGE_COLORS[type] || COLORS.textDim} size="xs">{type}</Tag>,
            <Code>{src}</Code>,
            <Code>{tgt}</Code>,
            <span style={{ color: COLORS.textMuted, fontSize: 11 }}>{meaning}</span>,
          ])}
        />
        <div style={{ marginTop: 12, background: COLORS.surface, border: `1px solid ${COLORS.border}`, borderRadius: 8, padding: 12 }}>
          <span style={{ color: COLORS.textMuted, fontSize: 12 }}>
            ⚡ The last 3 edges (<Tag color={COLORS.cyan} size="xs">references</Tag>) are created by a post-processing step: a URL extractor, a JIRA-key regex, and a fuzzy document name matcher scan the message content and create cross-platform links automatically.
          </span>
        </div>
      </Section>
    </div>
  );
}

// ─── TAB 3: Graph Visualisation ───────────────────────────────────────────────

function GraphView() {
  const [hoveredNode, setHoveredNode] = useState(null);

  const nodes = [
    { id: "sarah", type: "Person", label: "Sarah Chen", x: 360, y: 60, color: COLORS.green },
    { id: "james", type: "Person", label: "James Wright", x: 120, y: 200, color: COLORS.green },
    { id: "priya", type: "Person", label: "Priya Patel", x: 600, y: 200, color: COLORS.green },
    { id: "msg1", type: "Message", label: "Root message", x: 360, y: 200, color: COLORS.blue },
    { id: "msg2", type: "Message", label: "James reply", x: 210, y: 360, color: COLORS.blue },
    { id: "msg3", type: "Message", label: "Priya reply", x: 360, y: 380, color: COLORS.blue },
    { id: "msg4", type: "Message", label: "Sarah reply", x: 510, y: 360, color: COLORS.blue },
    { id: "channel", type: "Channel", label: "#billing-migration", x: 360, y: 490, color: COLORS.purple },
    { id: "pr", type: "Task", label: "GitHub PR #482", x: 120, y: 490, color: COLORS.accent },
    { id: "jira", type: "Task", label: "JIRA-1203", x: 600, y: 490, color: COLORS.accent },
    { id: "doc", type: "Document", label: "sync-failures doc", x: 120, y: 370, color: COLORS.cyan },
  ];

  const edges = [
    { from: "sarah", to: "msg1", label: "authored", color: COLORS.green },
    { from: "james", to: "msg2", label: "authored", color: COLORS.green },
    { from: "priya", to: "msg3", label: "authored", color: COLORS.green },
    { from: "sarah", to: "msg4", label: "authored", color: COLORS.green },
    { from: "msg2", to: "msg1", label: "replies_to", color: COLORS.blue },
    { from: "msg3", to: "msg1", label: "replies_to", color: COLORS.blue },
    { from: "msg4", to: "msg1", label: "replies_to", color: COLORS.blue },
    { from: "msg1", to: "channel", label: "posted_in", color: COLORS.purple },
    { from: "msg2", to: "channel", label: "posted_in", color: COLORS.purple },
    { from: "msg3", to: "channel", label: "posted_in", color: COLORS.purple },
    { from: "msg4", to: "channel", label: "posted_in", color: COLORS.purple },
    { from: "james", to: "msg1", label: "mentioned_in", color: COLORS.pink, dashed: true },
    { from: "sarah", to: "msg3", label: "mentioned_in", color: COLORS.pink, dashed: true },
    { from: "james", to: "msg1", label: "reacted_to 👍", color: COLORS.accent, dashed: true },
    { from: "priya", to: "msg1", label: "reacted_to 🔥", color: COLORS.accent, dashed: true },
    { from: "msg1", to: "pr", label: "references", color: COLORS.cyan },
    { from: "msg1", to: "jira", label: "references", color: COLORS.cyan },
    { from: "msg2", to: "doc", label: "references", color: COLORS.cyan },
  ];

  const getNode = (id) => nodes.find(n => n.id === id);

  const getConnectedIds = (nodeId) => {
    const connected = new Set([nodeId]);
    edges.forEach(e => {
      if (e.from === nodeId) connected.add(e.to);
      if (e.to === nodeId) connected.add(e.from);
    });
    return connected;
  };

  const connected = hoveredNode ? getConnectedIds(hoveredNode) : null;

  return (
    <div>
      <p style={{ color: COLORS.textDim, fontSize: 13, marginBottom: 16, lineHeight: 1.7 }}>
        The graph below shows all nodes and edges produced from the Slack thread. Hover any node to highlight its direct connections. This is what an agent traverses to build context.
      </p>
      <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        {[["Person", COLORS.green], ["Message", COLORS.blue], ["Channel", COLORS.purple], ["Task/Issue", COLORS.accent], ["Document", COLORS.cyan]].map(([t, c]) => (
          <div key={t} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: COLORS.textDim }}>
            <div style={{ width: 10, height: 10, borderRadius: "50%", background: c }} />
            {t}
          </div>
        ))}
        <div style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: COLORS.textDim, marginLeft: 8 }}>
          <div style={{ width: 20, height: 1.5, background: COLORS.textMuted, borderTop: "2px dashed " + COLORS.textMuted }} />
          social edges (reactions, mentions)
        </div>
      </div>
      <div style={{ background: COLORS.surface, border: `1px solid ${COLORS.border}`, borderRadius: 8, overflow: "hidden" }}>
        <svg width="100%" viewBox="0 0 720 560" style={{ display: "block" }}>
          <defs>
            {Object.entries(EDGE_COLORS).map(([type, color]) => (
              <marker key={type} id={`arrow-${type}`} markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                <path d="M0,0 L6,3 L0,6 Z" fill={color} opacity={0.8} />
              </marker>
            ))}
            <marker id="arrow-default" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 Z" fill={COLORS.textMuted} opacity={0.6} />
            </marker>
          </defs>
          {edges.map((edge, i) => {
            const fn = getNode(edge.from);
            const tn = getNode(edge.to);
            if (!fn || !tn) return null;
            const isActive = !connected || (connected.has(edge.from) && connected.has(edge.to));
            const dx = tn.x - fn.x, dy = tn.y - fn.y;
            const len = Math.sqrt(dx * dx + dy * dy);
            const r = 22;
            const sx = fn.x + (dx / len) * r, sy = fn.y + (dy / len) * r;
            const ex = tn.x - (dx / len) * r, ey = tn.y - (dy / len) * r;
            const mx = (sx + ex) / 2, my = (sy + ey) / 2;
            return (
              <g key={i} opacity={isActive ? 1 : 0.1} style={{ transition: "opacity 0.2s" }}>
                <line x1={sx} y1={sy} x2={ex} y2={ey}
                  stroke={edge.color} strokeWidth={isActive ? 1.5 : 1}
                  strokeDasharray={edge.dashed ? "4,3" : "none"}
                  markerEnd={`url(#arrow-default)`}
                  opacity={0.65} />
                <text x={mx} y={my - 4} textAnchor="middle" fontSize={9} fill={edge.color} opacity={0.85}
                  style={{ fontFamily: "monospace", pointerEvents: "none" }}>
                  {edge.label}
                </text>
              </g>
            );
          })}
          {nodes.map(node => {
            const isActive = !connected || connected.has(node.id);
            return (
              <g key={node.id} transform={`translate(${node.x},${node.y})`}
                onMouseEnter={() => setHoveredNode(node.id)}
                onMouseLeave={() => setHoveredNode(null)}
                style={{ cursor: "pointer", transition: "opacity 0.2s" }}
                opacity={isActive ? 1 : 0.15}>
                <circle r={22} fill={node.color + "22"} stroke={node.color}
                  strokeWidth={hoveredNode === node.id ? 2.5 : 1.5} />
                <text textAnchor="middle" y={4} fontSize={11} fontWeight={700}
                  fill={node.color} style={{ fontFamily: "monospace", pointerEvents: "none" }}>
                  {node.type[0]}
                </text>
                <text textAnchor="middle" y={35} fontSize={10} fill={COLORS.textDim}
                  style={{ fontFamily: "monospace", pointerEvents: "none" }}>
                  {node.label.length > 16 ? node.label.slice(0, 15) + "…" : node.label}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      {hoveredNode && (
        <div style={{ marginTop: 12, background: COLORS.surface, border: `1px solid ${COLORS.borderBright}`, borderRadius: 8, padding: 14 }}>
          <div style={{ color: COLORS.text, fontWeight: 700, fontSize: 13, marginBottom: 8 }}>
            {nodes.find(n => n.id === hoveredNode)?.label}
            <Tag color={nodes.find(n => n.id === hoveredNode)?.color || COLORS.textMuted} size="xs">{nodes.find(n => n.id === hoveredNode)?.type}</Tag>
          </div>
          <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
            <div>
              <div style={{ color: COLORS.textMuted, fontSize: 11, marginBottom: 6 }}>OUTGOING EDGES</div>
              {edges.filter(e => e.from === hoveredNode).map((e, i) => (
                <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
                  <Tag color={e.color} size="xs">{e.label}</Tag>
                  <span style={{ color: COLORS.textDim, fontSize: 11 }}>→ {getNode(e.to)?.label}</span>
                </div>
              ))}
            </div>
            <div>
              <div style={{ color: COLORS.textMuted, fontSize: 11, marginBottom: 6 }}>INCOMING EDGES</div>
              {edges.filter(e => e.to === hoveredNode).map((e, i) => (
                <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
                  <span style={{ color: COLORS.textDim, fontSize: 11 }}>{getNode(e.from)?.label}</span>
                  <Tag color={e.color} size="xs">{e.label}</Tag>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── TAB 4: Agent Context Building ────────────────────────────────────────────

function AgentView() {
  const [step, setStep] = useState(0);

  const steps = [
    {
      title: "1. Agent receives a task",
      prompt: "What's the status of the billing migration? Who is blocked and what decisions are pending?",
      description: "The agent needs to build context before it can answer. It starts with a semantic search.",
      code: `# Agent calls: search_entities(query, types, limit)
results = kg.search_entities(
    query="billing migration status",
    types=["Message", "Task", "Document"],
    limit=8
)
# → hybrid vector + FTS query against PostgreSQL`,
      sqlQuery: `SELECT e.id, e.entity_type, e.title, e.content,
       1 - (e.content_embedding <=> $1) AS vec_score,
       ts_rank(to_tsvector(e.content), plainto_tsquery($2)) AS fts_score
FROM entities e
WHERE e.expires_at > now()
  AND ($3::text[] IS NULL OR e.entity_type = ANY($3))
ORDER BY (0.7 * vec_score + 0.3 * fts_score) DESC
LIMIT 8;`,
      results: [
        { type: "Message", score: "0.94", label: "Sarah: 'billing migration was supposed to be done by EOW'" },
        { type: "Task", score: "0.91", label: "JIRA-1203: Salesforce sync failing in billing migration" },
        { type: "Message", score: "0.88", label: "Sarah: 'PR should unblock it. Once James reviews..'" },
        { type: "Task", score: "0.85", label: "GitHub PR #482: Fix duplicate charge bug" },
        { type: "Document", score: "0.81", label: "Confluence: Q1 Billing Migration Plan" },
      ]
    },
    {
      title: "2. Traverse 1-2 hops from seed nodes",
      description: "The agent takes the top search results as seed nodes and traverses the graph to gather surrounding context — who wrote them, what they replied to, what else they reference.",
      code: `# Agent calls: traverse(entity_ids, depth=2)
context = kg.traverse(
    seed_ids=[msg3_id, jira1203_id, pr482_id],
    depth=2,
    max_nodes=30
)`,
      sqlQuery: `WITH RECURSIVE traversal AS (
  -- seed nodes
  SELECT id, entity_type, content, 0 AS depth
  FROM entities WHERE id = ANY($1)
  UNION ALL
  SELECT e.id, e.entity_type, e.content, t.depth + 1
  FROM traversal t
  JOIN edges ed ON (ed.source_entity_id = t.id OR ed.target_entity_id = t.id)
  JOIN entities e ON e.id = CASE
    WHEN ed.source_entity_id = t.id THEN ed.target_entity_id
    ELSE ed.source_entity_id END
  WHERE t.depth < 2
)
SELECT DISTINCT * FROM traversal LIMIT 30;`,
      results: [
        { type: "Message", score: "depth 0", label: "Priya: 'billing migration supposed to be done EOW @sarah'" },
        { type: "Message", score: "depth 1", label: "Sarah: 'The PR should unblock it. Once James reviews...'" },
        { type: "Message", score: "depth 1", label: "Sarah: 'fix for duplicate charge bug. PR up: github.com/...' " },
        { type: "Message", score: "depth 1", label: "James: 'OAuth token refresh failing silently'" },
        { type: "Person", score: "via authored", label: "Sarah Chen — 3 messages authored" },
        { type: "Person", score: "via authored", label: "James Wright — mentioned, authored 1 reply" },
        { type: "Channel", score: "via posted_in", label: "#billing-migration — thread context" },
        { type: "Document", score: "via references", label: "sync-failures doc — referenced by James' reply" },
      ]
    },
    {
      title: "3. Resolve persons for full cross-platform context",
      description: "Every Person node found during traversal is enriched with their full cross-platform profile. The agent now knows that 'James' in Slack, 'jwright' in GitHub, and 'accountId:5f8...' in JIRA are the same person.",
      code: `# Agent calls: get_person_context(email)
james = kg.get_person_context("james.wright@acme.com")`,
      sqlQuery: `SELECT p.canonical_email, p.display_name,
       json_agg(json_build_object(
         'platform', pi.platform,
         'user_id', pi.platform_user_id,
         'username', pi.platform_username
       )) AS identities,
       (SELECT count(*) FROM edges e JOIN entities en
        ON en.id = e.source_entity_id
        WHERE e.source_person_id = p.id
          AND e.edge_type = 'authored'
          AND en.created_at > now() - interval '30 days'
       ) AS messages_last_30d
FROM persons p
JOIN platform_identities pi ON pi.person_id = p.id
WHERE p.canonical_email = $1
GROUP BY p.id;`,
      results: [
        { type: "Person", score: "resolved", label: "James Wright — james.wright@acme.com" },
        { type: "platform_identity", score: "slack", label: "U0JAMES / james.wright" },
        { type: "platform_identity", score: "github", label: "jwright (contributor to billing repo)" },
        { type: "platform_identity", score: "jira", label: "accountId:5f8abc… — assignee on JIRA-1203" },
        { type: "platform_identity", score: "salesforce", label: "user:0053X… (CRM access)" },
      ]
    },
    {
      title: "4. Pack context window and infer",
      description: "All retrieved nodes are serialised into a structured context block and injected into the agent's prompt. The agent can now answer with full situational awareness across Slack, GitHub, JIRA, and Salesforce.",
      code: `# Serialise graph context for LLM prompt
context_block = kg.pack_context(nodes, max_tokens=4000)`,
      sqlQuery: `-- No SQL — this is the final prompt assembly step
-- The agent packs nodes in recency + relevance order,
-- summarising threads > 3 messages,
-- truncating document content to ~300 chars each,
-- and structuring output as typed sections.`,
      results: null,
      contextBlock: `## Billing Migration — Current Status Context

### People involved
- **Sarah Chen** (sarah.chen@acme.com) — Slack: @sarah.chen | GitHub: schcn | JIRA assignee
- **James Wright** (james.wright@acme.com) — Slack: @james | GitHub: jwright | JIRA-1203 assignee  
- **Priya Patel** — Stakeholder, flagged EOW deadline

### Slack thread (#billing-migration, 2025-04-17)
Sarah posted PR #482 fix for duplicate charge bug and flagged JIRA-1203.
James confirmed OAuth token refresh failing silently as root cause.
Priya raised concern: migration was due EOW. Sarah believes PR will unblock.

### GitHub PR #482 (status: open, 0 reviews)
Title: "Fix duplicate charge bug in billing sync"
Branch: fix/billing-duplicate-charge — waiting for James to review

### JIRA-1203 (status: In Progress, assignee: James Wright)  
"Salesforce sync failing in billing migration" — Priority: High

### Confluence: sync-failures doc
Referenced by James — documents known Salesforce OAuth issues.

### ⚠ Agent inference
Blocker: PR #482 awaiting James Wright review. JIRA-1203 unresolved.
Risk: EOW deadline raised by Priya is at risk if review not completed today.`,
    }
  ];

  const s = steps[step];

  return (
    <div>
      <p style={{ color: COLORS.textDim, fontSize: 13, marginBottom: 20, lineHeight: 1.7 }}>
        Walk through the exact sequence an agent follows to answer <em style={{ color: COLORS.text }}>"What's the status of the billing migration?"</em> — from search to context to inference.
      </p>

      {/* Step tabs */}
      <div style={{ display: "flex", gap: 4, marginBottom: 20, flexWrap: "wrap" }}>
        {steps.map((st, i) => (
          <button key={i} onClick={() => setStep(i)} style={{
            background: step === i ? COLORS.accent + "22" : COLORS.surface,
            border: `1px solid ${step === i ? COLORS.accent : COLORS.border}`,
            color: step === i ? COLORS.accent : COLORS.textMuted,
            borderRadius: 6, padding: "6px 14px", cursor: "pointer",
            fontSize: 12, fontWeight: 600, fontFamily: "monospace",
            transition: "all 0.15s",
          }}>{st.title}</button>
        ))}
      </div>

      <div style={{ background: COLORS.surface, border: `1px solid ${COLORS.border}`, borderRadius: 10, overflow: "hidden" }}>
        {step === 0 && (
          <div style={{ background: "#080a0f", padding: "14px 18px", borderBottom: `1px solid ${COLORS.border}`, display: "flex", gap: 10, alignItems: "flex-start" }}>
            <div style={{ color: COLORS.accent, fontSize: 12, marginTop: 1 }}>USER QUERY</div>
            <div style={{ color: COLORS.text, fontSize: 14, fontStyle: "italic" }}>"{s.prompt}"</div>
          </div>
        )}
        <div style={{ padding: 20 }}>
          <p style={{ color: COLORS.textDim, fontSize: 13, lineHeight: 1.7, margin: "0 0 16px" }}>{s.description}</p>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 16 }}>
            <div>
              <div style={{ color: COLORS.textMuted, fontWeight: 700, fontSize: 11, letterSpacing: "0.06em", marginBottom: 8 }}>AGENT CODE</div>
              <Code block>{s.code}</Code>
            </div>
            <div>
              <div style={{ color: COLORS.textMuted, fontWeight: 700, fontSize: 11, letterSpacing: "0.06em", marginBottom: 8 }}>SQL EXECUTED</div>
              <Code block>{s.sqlQuery}</Code>
            </div>
          </div>

          {s.results && (
            <div>
              <div style={{ color: COLORS.textMuted, fontWeight: 700, fontSize: 11, letterSpacing: "0.06em", marginBottom: 8 }}>NODES RETRIEVED</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {s.results.map((r, i) => (
                  <div key={i} style={{
                    display: "flex", gap: 10, alignItems: "center",
                    background: "#080a0f", border: `1px solid ${COLORS.border}`,
                    borderRadius: 6, padding: "8px 12px",
                  }}>
                    <Tag color={ENTITY_COLORS[r.type] || COLORS.textDim} size="xs">{r.type}</Tag>
                    <Tag color={COLORS.textMuted} size="xs">{r.score}</Tag>
                    <span style={{ color: COLORS.textDim, fontSize: 12, flex: 1 }}>{r.label}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {s.contextBlock && (
            <div>
              <div style={{ color: COLORS.textMuted, fontWeight: 700, fontSize: 11, letterSpacing: "0.06em", marginBottom: 8 }}>ASSEMBLED CONTEXT BLOCK (injected into agent prompt)</div>
              <div style={{
                background: "#080a0f", border: `1px solid ${COLORS.borderBright}`,
                borderRadius: 8, padding: 16, fontFamily: "monospace",
                fontSize: 12, color: COLORS.textDim, lineHeight: 1.8,
                whiteSpace: "pre-wrap",
              }}>
                {s.contextBlock.split('\n').map((line, i) => {
                  const color = line.startsWith('##') ? COLORS.accent
                    : line.startsWith('###') ? COLORS.blue
                    : line.startsWith('⚠') ? COLORS.red
                    : line.startsWith('-') ? COLORS.textDim
                    : COLORS.textMuted;
                  return <div key={i} style={{ color }}>{line || '\u00A0'}</div>;
                })}
              </div>
            </div>
          )}
        </div>
      </div>

      <div style={{ marginTop: 16, background: COLORS.surface, border: `1px solid ${COLORS.borderBright}`, borderRadius: 8, padding: 14 }}>
        <div style={{ color: COLORS.accent, fontWeight: 700, fontSize: 12, marginBottom: 8 }}>HOW THIS COMPARES TO A CODING AGENT</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <div>
            <div style={{ color: COLORS.textMuted, fontSize: 11, marginBottom: 8 }}>CODING AGENT (Claude Code)</div>
            {[["grep / semantic search", "→ find relevant files"], ["read_file", "→ get full content"], ["follow imports", "→ traverse dependencies"], ["understand structure", "→ project-wide context"]].map(([a, b], i) => (
              <div key={i} style={{ display: "flex", gap: 8, color: COLORS.textDim, fontSize: 12, marginBottom: 4 }}>
                <Code>{a}</Code><span>{b}</span>
              </div>
            ))}
          </div>
          <div>
            <div style={{ color: COLORS.textMuted, fontSize: 11, marginBottom: 8 }}>KNOWLEDGE GRAPH AGENT</div>
            {[["search_entities(query)", "→ find relevant nodes"], ["get_entity(id)", "→ get full content"], ["traverse(ids, depth=2)", "→ follow relationships"], ["get_project_context()", "→ workspace-wide context"]].map(([a, b], i) => (
              <div key={i} style={{ display: "flex", gap: 8, color: COLORS.textDim, fontSize: 12, marginBottom: 4 }}>
                <Code>{a}</Code><span>{b}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Main App ─────────────────────────────────────────────────────────────────

export default function App() {
  const [tab, setTab] = useState(0);

  const tabs = [
    { label: "1 · Schema", icon: "⬡" },
    { label: "2 · Slack → Graph", icon: "→" },
    { label: "3 · Graph Visual", icon: "◎" },
    { label: "4 · Agent Flow", icon: "⚡" },
  ];

  const views = [SchemaView, MappingView, GraphView, AgentView];
  const View = views[tab];

  return (
    <div style={{ background: COLORS.bg, minHeight: "100vh", fontFamily: "'IBM Plex Mono', 'Courier New', monospace", color: COLORS.text }}>
      <div style={{ maxWidth: 860, margin: "0 auto", padding: "28px 20px" }}>
        {/* Header */}
        <div style={{ marginBottom: 28 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 6 }}>
            <span style={{ fontSize: 11, color: COLORS.accent, fontWeight: 700, letterSpacing: "0.1em" }}>KNOWLEDGE GRAPH</span>
            <span style={{ fontSize: 11, color: COLORS.textMuted, letterSpacing: "0.06em" }}>DATA STRUCTURE EXPLORER</span>
          </div>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: COLORS.text, margin: 0, lineHeight: 1.3 }}>
            How a Slack thread becomes a traversable knowledge graph
          </h1>
          <p style={{ color: COLORS.textMuted, fontSize: 12, marginTop: 6 }}>
            Schema · Entity mapping · Graph visualisation · Agent context building
          </p>
        </div>

        {/* Tabs */}
        <div style={{ display: "flex", gap: 3, marginBottom: 24, borderBottom: `1px solid ${COLORS.border}`, paddingBottom: 0 }}>
          {tabs.map((t, i) => (
            <button key={i} onClick={() => setTab(i)} style={{
              background: "none", border: "none", borderBottom: tab === i ? `2px solid ${COLORS.accent}` : "2px solid transparent",
              color: tab === i ? COLORS.accent : COLORS.textMuted,
              padding: "8px 16px", cursor: "pointer", fontSize: 12, fontWeight: 700,
              fontFamily: "inherit", marginBottom: -1, transition: "all 0.15s",
              letterSpacing: "0.04em",
            }}>{t.icon} {t.label}</button>
          ))}
        </div>

        <View />

        <div style={{ marginTop: 32, borderTop: `1px solid ${COLORS.border}`, paddingTop: 16, color: COLORS.textMuted, fontSize: 11, lineHeight: 1.7 }}>
          This single Slack thread produces <strong style={{ color: COLORS.textDim }}>5 entities</strong>, <strong style={{ color: COLORS.textDim }}>3 persons</strong>, <strong style={{ color: COLORS.textDim }}>3 platform_identity rows</strong>, and <strong style={{ color: COLORS.textDim }}>15+ edges</strong>.
          A real workspace with 200 active channels generates tens of thousands of nodes and hundreds of thousands of edges per 3-month window.
          The graph is queryable in milliseconds via indexed PostgreSQL — no API calls required at inference time.
        </div>
      </div>
    </div>
  );
}
