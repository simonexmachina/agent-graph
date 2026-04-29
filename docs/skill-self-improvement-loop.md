# Skill Self-Improvement Loop

## Problem

Agent skills are static. A human writes a retrieval strategy ("to answer X, do search → get_entity → traverse"), and the agent follows the recipe forever — regardless of whether it works well, whether the user keeps asking variations the skill handles poorly, or whether better strategies emerge from experience.

The graph gives agents data. Skills give agents strategy. But strategy doesn't learn.

## Core Idea

A meta-loop that observes how skills perform against real queries, detects patterns in successes and failures, and rewrites skills to encode better retrieval strategies. The output isn't cached answers — it's **new code** that generalises.

Three layers:

```
┌─────────────────────────────────────────┐
│  Meta-Loop (learning)                   │
│  Watches skill performance, detects     │
│  patterns, triggers refactoring         │
├─────────────────────────────────────────┤
│  Skills (strategy)                      │
│  Composable retrieval patterns that     │
│  turn graph primitives into answers     │
├─────────────────────────────────────────┤
│  Graph (data)                           │
│  Entities, edges, embeddings            │
│  The raw material                       │
└─────────────────────────────────────────┘
```

## How It Works

### 1. Reasoning Traces as Training Data

Every query the agent handles produces a reasoning trace:

```
Query: "What did Sarah say about the Kubernetes migration?"
Steps:
  1. search_entities("Sarah Kubernetes migration") → 3 results
  2. get_entity(entity_id) → Sarah Chen, Person
  3. get_edges(entity_id, type="authored") → 47 messages
  4. search_entities("Kubernetes migration") → 12 results
  5. traverse_graph(start=sarah_id, edge_types=["authored","mentioned"]) → subgraph
  6. ... filtered manually in prompt ...
Result: Answer synthesised from 4 relevant messages
Latency: 3.2s across 5 tool calls
User satisfaction: implicit (no correction, follow-up was on-topic)
```

These traces accumulate. They're the raw signal for the meta-loop.

### 2. Pattern Detection

The meta-loop periodically analyses reasoning traces to find:

- **Recurring query shapes**: "person + topic" queries, "timeline of X" queries, "compare A and B" queries
- **Inefficient strategies**: queries that take many hops to reach relevant data, or that retrieve too much and filter in-prompt
- **Failed retrievals**: queries where the agent couldn't find what it needed, or where the user corrected the answer
- **Successful compositions**: sequences of primitives that consistently produce good results

Pattern detection could be:
- **Rule-based**: simple heuristics on trace structure (e.g., "more than 5 tool calls for a factual question = inefficient")
- **Embedding-based**: cluster similar queries by their trace shapes, identify which clusters have high vs. low success rates
- **LLM-based**: periodically feed a batch of traces to an LLM and ask "what retrieval patterns are emerging? which ones work? which don't?"

### 3. Skill Generation & Refactoring

When the meta-loop identifies a pattern worth encoding, it generates or refactors a skill:

**Before (generic):**
```
To answer questions about a person's views on a topic:
1. Search for the person
2. Get all their authored messages
3. Search for the topic
4. Cross-reference in prompt
```

**After (learned):**
```
To answer questions about a person's views on a topic:
1. Search for Person entity by name
2. Traverse "authored" edges filtered to entities that have
   "mentions" edges to topic-matching entities
3. Rank by recency
4. Return top 5 with source attribution
```

The refined skill is fewer tool calls, more targeted traversal, and produces better-ranked results.

### 4. Skill Registry & Selection

Skills live in a registry. When a query arrives, the agent (or a router) selects which skill(s) to apply:

```python
class SkillRegistry:
    skills: list[Skill]

    async def match(self, query: str, context: dict) -> list[ScoredSkill]:
        """Return skills ranked by relevance to this query."""

    async def register(self, skill: Skill) -> None:
        """Add a new or updated skill."""

    async def deprecate(self, skill_id: str, reason: str) -> None:
        """Mark a skill as superseded."""
```

Each skill has:
- **Pattern**: what kind of query it handles (embedding + description)
- **Strategy**: the retrieval steps (code or structured plan)
- **Provenance**: which traces inspired it, when it was created/last updated
- **Performance metrics**: success rate, avg latency, avg tool calls

### 5. The Loop

```
User query
    │
    ▼
Skill selection (match query → best skill)
    │
    ▼
Skill execution (run retrieval strategy against graph)
    │
    ▼
Reasoning trace recorded
    │
    ▼
Response to user
    │
    ▼
    ┌──────────────────────────────┐
    │  Meta-loop (async/periodic)  │
    │                              │
    │  Analyse recent traces       │
    │  Detect patterns             │
    │  Score existing skills       │
    │  Generate/refactor skills    │
    │  Update registry             │
    └──────────────────────────────┘
```

The meta-loop runs asynchronously — not on the hot path of a query. It could be:
- **Periodic**: every N hours, review accumulated traces
- **Threshold-triggered**: when a skill's success rate drops below X, or when N similar queries have no matching skill
- **On-demand**: user or admin triggers a review

## Key Design Tensions

### Refactor vs. Compose

Sometimes the right move is a new specialised skill. Sometimes it's realising two existing skills compose well and just need a wrapper. The meta-loop needs to distinguish:

- **"This skill is bad"** → refactor the strategy
- **"These skills aren't being combined properly"** → create a composition skill
- **"No skill exists for this pattern"** → generate a new one
- **"This skill is good but slow"** → optimise (fewer hops, better filters)

### Stability vs. Exploration

If the loop is too aggressive, skills churn constantly and the agent's behaviour becomes unpredictable. If it's too conservative, skills calcify. Need:

- **Canary deployments**: new/refactored skills run alongside existing ones, with a fraction of traffic
- **Rollback**: if a refactored skill performs worse, revert
- **Cool-down**: don't refactor the same skill twice within N hours

### Skill Granularity

Too coarse: "here's how to answer any question" — useless, just a system prompt.
Too fine: "here's how to answer 'what did Sarah say about K8s'" — just caching.

The sweet spot is **reusable retrieval patterns** that generalise across a class of queries without being so abstract they lose their edge. "Person + topic retrieval" is a good granularity. "Any question about anything" is too broad. "Sarah + Kubernetes" is too narrow.

### Human Override

Skills should be inspectable and editable. The meta-loop proposes changes; a human (or a human-in-the-loop policy) can approve, reject, or edit. Skills carry provenance — you can always see why a skill exists, what traces inspired it, and what it replaced.

## Connection to AgentGraph Architecture

This sits naturally on top of the existing stack:

- **Graph primitives** (`search_entities`, `get_entity`, `traverse_graph`, `query_by_filter`) remain the foundation
- **Skills** are compositions of primitives — they don't replace the MCP/CLI interface, they use it
- **Reasoning traces** extend the existing observation model — just as browser observations drive graph construction, reasoning observations drive skill evolution
- **The Horizon metaphor applies**: skills that haven't been used within a retention window could decay/deprecate, just like entities

## Connection to neo4j-agent-memory

Their reasoning memory (traces, tool calls, success/failure) provides exactly the raw signal this loop needs. Whether we use their implementation or build our own trace store, the schema is similar:

- `ReasoningTrace` → linked to triggering message/query
- `ReasoningStep` → thought + action
- `ToolCall` → tool name, arguments, result, duration, status
- Traces are queryable: "find all traces where tool X was called for queries matching pattern Y"

## Open Questions

1. **Where do skills live?** Files on disk (like AgentSkills SKILL.md)? In the graph itself? A separate registry?

2. **What's the skill representation?** Structured plans (JSON/YAML)? Executable code (Python functions)? Natural language instructions? Probably starts as natural language and evolves toward code.

3. **Who runs the meta-loop?** A separate agent? A cron job? Part of the main agent's heartbeat? Likely a background process that doesn't compete for resources with query handling.

4. **How do we measure "success"?** Explicit feedback (thumbs up/down)? Implicit signals (user didn't correct, asked a follow-up)? Latency? Number of tool calls? Probably a composite score.

5. **How do we bootstrap?** Cold start with a set of hand-written skills? Let the agent run with raw primitives and generate skills from the first N traces? Both?

6. **Multi-user**: If multiple users share a graph, should skills be per-user (personalised retrieval strategies) or shared (collective intelligence)?

## Relationship to SaaSmageddon Thesis

> "The database IS the application layer"

If the graph is the database, skills are the application layer. But instead of humans writing and maintaining that application layer (traditional SaaS), the meta-loop writes and maintains it. The "application" evolves continuously based on usage — no product manager, no sprint planning, no feature requests. Just the loop watching what works and making it better.

This is what "agent-first platform" looks like in practice: the agent doesn't just query data, it continuously improves *how* it queries data.
