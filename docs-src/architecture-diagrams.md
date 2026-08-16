+++
title = "Architecture diagram options"
description = "Alternative diagrams for explaining how observation, direct fetch, refresh, and expiry shape the AgentGraph architecture."
nav_title = "Architecture diagrams"
nav_hidden = true
section = "Start"
order = 45
summary = "Four ways to organize the same architecture around Observe, Fetch, Refresh, and Expiry."
output = "architecture-diagrams.html"
source_path = "docs-src/architecture-diagrams.md"
+++

Each option describes the same system behavior with a different visual emphasis. Observe, Fetch, and Refresh bring content into or update the local graph through connector packages. Expiry applies the retention model to content already stored in the graph.

## 1. Converging flows

Three parallel inputs converge on the connector boundary and local graph. Expiry leaves the graph as a separate lifecycle path, while the agent-facing read path stays visible but secondary.

<figure class="architecture-figure" tabindex="0">
  <img src="/assets/diagrams/architecture-converging-flows-dark.svg" alt="Observe, Fetch, and Refresh converge on connector packages that read selected services and write to the local graph. The graph is available to an agent through MCP and the CLI, while a separate retention path expires content.">
  <figcaption>Best balance of lifecycle accuracy, architectural context, and scanability.</figcaption>
</figure>

## 2. Comparable lanes

Each lifecycle behavior gets a complete trigger-to-outcome lane. Shared components repeat so the differences between attention, on-demand retrieval, background updates, and retention are explicit.

<figure class="architecture-figure" tabindex="0">
  <img src="/assets/diagrams/architecture-four-lanes-dark.svg" alt="Four horizontal lanes compare Observe from a focused browser page, Fetch from an agent or CLI request, Refresh from polling known resources, and Expiry through the retention model.">
  <figcaption>Clearest behavioral comparison, with more repetition and less emphasis on shared infrastructure.</figcaption>
</figure>

## 3. Central hub

The local graph is the visual center. Observe, Fetch, and Refresh surround the connector path; Expiry and the agent-facing access path leave the graph in separate directions.

<figure class="architecture-figure" tabindex="0">
  <img src="/assets/diagrams/architecture-central-hub-dark.svg" alt="A central local graph receives translated content from connector packages. Observe, Fetch, and Refresh feed the connectors, selected services supply the content, agents access the graph through MCP and the CLI, and Expiry removes content according to retention.">
  <figcaption>Most compact topology view and closest to the current architecture overview.</figcaption>
</figure>

## 4. Lifecycle loop

The graph is shown as a maintained working set. Observe and Fetch discover specific resources, Refresh sends known resources back through connector fetch logic, and Expiry removes content that falls outside retention.

<figure class="architecture-figure" tabindex="0">
  <img src="/assets/diagrams/architecture-lifecycle-loop-dark.svg" alt="Observe and Fetch identify resources for connector resolution and storage in the local graph. Refresh loops known resources back through connectors, while Expiry removes graph content outside the retention model.">
  <figcaption>Strongest explanation of how the stored working set changes over time.</figcaption>
</figure>
