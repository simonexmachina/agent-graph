import { DEFAULT_SERVER_BASE_URL, getServerBaseUrl, setServerBaseUrl } from "./lib/config.js";

interface RuntimeResponse {
  ok: boolean;
  meta?: DwellMeta;
  error?: string;
}

interface DwellMeta {
  url_patterns: string[];
  dwell_threshold_ms: number;
}

function setStatus(message: string, variant: "neutral" | "success" | "error" = "neutral"): void {
  const statusEl = document.getElementById("form-status");
  if (!statusEl) return;
  statusEl.textContent = message;
  statusEl.className = "form-status";
  if (variant !== "neutral") {
    statusEl.classList.add(`form-status--${variant}`);
  }
}

async function notifyBackground(): Promise<DwellMeta> {
  const response = await chrome.runtime.sendMessage({ type: "server_url_updated" }) as RuntimeResponse;
  if (!response.ok) {
    throw new Error(response.error ?? "Failed to reload extension settings");
  }
  if (!response.meta) {
    throw new Error("Server did not return observation metadata");
  }
  return response.meta;
}

async function refreshObservationMetadata(): Promise<DwellMeta> {
  const response = await chrome.runtime.sendMessage({ type: "reload_url_patterns" }) as RuntimeResponse;
  if (!response.ok) {
    throw new Error(response.error ?? "Failed to refresh observation metadata");
  }
  if (!response.meta) {
    throw new Error("Server did not return observation metadata");
  }
  return response.meta;
}

function renderObservationMetadata(meta: DwellMeta): void {
  const count = document.getElementById("observation-pattern-count");
  if (count) count.textContent = String(meta.url_patterns.length);

  const list = document.getElementById("observation-patterns");
  if (!list) return;
  list.replaceChildren(
    ...meta.url_patterns.map((pattern) => {
      const item = document.createElement("li");
      item.textContent = pattern;
      return item;
    }),
  );
}

function renderExtensionVersion(): void {
  const version = document.getElementById("extension-version");
  if (version) version.textContent = chrome.runtime.getManifest().version;
}

async function loadForm(): Promise<void> {
  const input = document.getElementById("server-url") as HTMLInputElement | null;
  if (!input) return;
  input.value = await getServerBaseUrl();
  renderExtensionVersion();
  renderObservationMetadata(await refreshObservationMetadata());
  setStatus("");
}

async function saveServerUrl(event: SubmitEvent): Promise<void> {
  event.preventDefault();
  const input = document.getElementById("server-url") as HTMLInputElement | null;
  if (!input) return;

  try {
    const normalizedValue = await setServerBaseUrl(input.value);
    input.value = normalizedValue;
    renderObservationMetadata(await notifyBackground());
    setStatus(`Saved ${normalizedValue}`, "success");
  } catch (error: unknown) {
    setStatus(error instanceof Error ? error.message : "Failed to save server URL", "error");
  }
}

async function resetDefaults(): Promise<void> {
  const input = document.getElementById("server-url") as HTMLInputElement | null;
  if (!input) return;
  input.value = DEFAULT_SERVER_BASE_URL;
  await setServerBaseUrl(DEFAULT_SERVER_BASE_URL);
  renderObservationMetadata(await notifyBackground());
  setStatus(`Reset to ${DEFAULT_SERVER_BASE_URL}`, "success");
}

async function reloadMetadata(): Promise<void> {
  const button = document.getElementById("refresh-metadata") as HTMLButtonElement | null;
  if (button) {
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
  }
  setStatus("Refreshing observation patterns...");
  try {
    const meta = await refreshObservationMetadata();
    renderObservationMetadata(meta);
    setStatus(`Observation patterns refreshed (${meta.url_patterns.length})`, "success");
  } catch (error: unknown) {
    setStatus(error instanceof Error ? error.message : "Failed to refresh observation metadata", "error");
  } finally {
    if (button) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  }
}

document.getElementById("server-form")?.addEventListener("submit", (event) => {
  saveServerUrl(event).catch(console.error);
});

document.getElementById("reset-defaults")?.addEventListener("click", () => {
  resetDefaults().catch(console.error);
});

document.getElementById("refresh-metadata")?.addEventListener("click", () => {
  reloadMetadata().catch(console.error);
});

loadForm().catch(console.error);
