export const DEFAULT_SERVER_BASE_URL = "http://localhost:8765";
export const SERVER_BASE_URL_KEY = "agentgraph_server_base_url";

const ALLOWED_HOSTNAMES = new Set(["localhost", "127.0.0.1"]);

function isValidPort(port: string): boolean {
  if (!/^\d+$/.test(port)) return false;
  const value = Number(port);
  return Number.isInteger(value) && value >= 1 && value <= 65535;
}

export function normalizeServerBaseUrl(value: string): string {
  const trimmedValue = value.trim();
  let url: URL;
  try {
    url = new URL(trimmedValue);
  } catch {
    throw new Error("Enter a full URL such as http://localhost:8765");
  }

  if (url.protocol !== "http:") {
    throw new Error("Only http:// URLs are supported");
  }
  if (!ALLOWED_HOSTNAMES.has(url.hostname)) {
    throw new Error("Server URL must use localhost or 127.0.0.1");
  }
  if (!isValidPort(url.port)) {
    throw new Error("Server URL must include an explicit port");
  }
  if (url.username || url.password) {
    throw new Error("Server URL must not include credentials");
  }
  if (url.search || url.hash) {
    throw new Error("Server URL must not include query params or a fragment");
  }
  if (url.pathname !== "/" && url.pathname !== "") {
    throw new Error("Server URL must not include a path");
  }

  return `http://${url.hostname}:${url.port}`;
}

export function getHealthUrl(serverBaseUrl: string): string {
  return `${serverBaseUrl}/health`;
}

export function getMetaUrl(serverBaseUrl: string): string {
  return `${serverBaseUrl}/api/cli/meta`;
}

export function getReportDwellUrl(serverBaseUrl: string): string {
  return `${serverBaseUrl}/report-dwell`;
}

export async function getServerBaseUrl(): Promise<string> {
  const result = await chrome.storage.local.get(SERVER_BASE_URL_KEY);
  const storedValue = result[SERVER_BASE_URL_KEY];
  if (typeof storedValue !== "string" || storedValue.length === 0) {
    return DEFAULT_SERVER_BASE_URL;
  }
  try {
    return normalizeServerBaseUrl(storedValue);
  } catch {
    return DEFAULT_SERVER_BASE_URL;
  }
}

export async function setServerBaseUrl(value: string): Promise<string> {
  const normalizedValue = normalizeServerBaseUrl(value);
  await chrome.storage.local.set({ [SERVER_BASE_URL_KEY]: normalizedValue });
  return normalizedValue;
}
