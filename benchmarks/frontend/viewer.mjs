import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import { performance } from 'node:perf_hooks';

const baseUrl = process.env.AGENTGRAPH_BENCHMARK_URL;
const output = process.env.AGENTGRAPH_BENCHMARK_OUTPUT || '.benchmarks/frontend.json';

if (!baseUrl) {
  throw new Error('Set AGENTGRAPH_BENCHMARK_URL to the running AgentGraph server URL.');
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
const failures = [];
page.on('requestfailed', request => failures.push(request.url()));

async function measure(name, action) {
  const start = performance.now();
  await action();
  const elapsedMs = performance.now() - start;
  const diagnostics = await page.evaluate(() => ({
    longTasks: performance.getEntriesByType('longtask').length,
    resources: performance.getEntriesByType('resource').length,
  }));
  return { name, kind: 'frontend', elapsed_ms: elapsedMs, ...diagnostics };
}

try {
  const workloads = [];
  workloads.push(await measure('viewer.initial_render', async () => {
    await page.goto(`${baseUrl.replace(/\/$/, '')}/viewer`, { waitUntil: 'networkidle' });
    await page.locator('#cy').waitFor({ state: 'visible' });
  }));
  workloads.push(await measure('viewer.graph_layout', async () => {
    await page.waitForFunction(() => {
      const graph = window.__agentGraphViewer?.cy;
      return graph && graph.nodes().length > 0 && graph.nodes().every(node => {
        const position = node.position();
        return Number.isFinite(position.x) && Number.isFinite(position.y);
      });
    });
  }));
  workloads.push(await measure('viewer.search_to_results', async () => {
    const search = page.locator('#search-input');
    await search.fill('shared context');
    await search.press('Enter');
    await page.waitForResponse(response => response.url().includes('/api/graph/nodes'));
  }));
  workloads.push(await measure('viewer.list_paging', async () => {
    await page.locator('#list-tab').click();
    await page.locator('#node-list-body tr').first().waitFor({ state: 'visible' });
  }));
  workloads.push(await measure('viewer.entity_detail', async () => {
    await page.locator('#node-list-body tr').first().click();
    await page.locator('#detail').waitFor({ state: 'visible' });
  }));
  await mkdir(dirname(output), { recursive: true });
  await writeFile(output, `${JSON.stringify({ schema_version: 1, workloads, failures }, null, 2)}\n`);
  if (failures.length) process.exitCode = 1;
} finally {
  await browser.close();
}
