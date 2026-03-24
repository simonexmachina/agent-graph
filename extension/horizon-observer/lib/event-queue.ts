/**
 * Persistent event queue with offline resilience.
 *
 * Events are written to chrome.storage.local before sending.
 * On success they are removed; on failure they stay for retry.
 * A flush is attempted whenever the service worker starts and on each
 * new event.
 */

export interface ObserveEvent {
  type: "focus" | "blur";
  url: string;
  title?: string;
  tab_id: number;
  timestamp: string; // ISO-8601
}

const QUEUE_KEY = "agentgraph_event_queue";
const SERVER_URL = "http://localhost:8765/observe";
const MAX_QUEUE_SIZE = 500;

async function readQueue(): Promise<ObserveEvent[]> {
  const result = await chrome.storage.local.get(QUEUE_KEY);
  return (result[QUEUE_KEY] as ObserveEvent[] | undefined) ?? [];
}

async function writeQueue(events: ObserveEvent[]): Promise<void> {
  await chrome.storage.local.set({ [QUEUE_KEY]: events });
}

/** Append an event to persistent storage, then attempt to flush. */
export async function enqueue(event: ObserveEvent): Promise<void> {
  const queue = await readQueue();
  // Prevent unbounded growth if server is unreachable for a long time
  if (queue.length >= MAX_QUEUE_SIZE) {
    queue.shift(); // drop oldest
  }
  queue.push(event);
  await writeQueue(queue);
  await flush();
}

/**
 * Attempt to deliver all queued events to the server.
 * Events sent successfully are removed; failures are kept for the next flush.
 */
export async function flush(): Promise<void> {
  const queue = await readQueue();
  if (queue.length === 0) return;

  const remaining: ObserveEvent[] = [];

  for (const event of queue) {
    const sent = await sendEvent(event);
    if (!sent) {
      remaining.push(event);
    }
  }

  await writeQueue(remaining);
}

async function sendEvent(event: ObserveEvent): Promise<boolean> {
  try {
    const response = await fetch(SERVER_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(event),
    });
    return response.ok;
  } catch {
    return false;
  }
}
