import { DEFAULT_SERVER_BASE_URL, getServerBaseUrl, setServerBaseUrl } from "./lib/config.js";

interface RuntimeResponse {
  ok: boolean;
  error?: string;
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

async function notifyBackground(): Promise<void> {
  const response = await chrome.runtime.sendMessage({ type: "server_url_updated" }) as RuntimeResponse;
  if (!response.ok) {
    throw new Error(response.error ?? "Failed to reload extension settings");
  }
}

async function loadForm(): Promise<void> {
  const input = document.getElementById("server-url") as HTMLInputElement | null;
  if (!input) return;
  input.value = await getServerBaseUrl();
  setStatus("");
}

async function saveServerUrl(event: SubmitEvent): Promise<void> {
  event.preventDefault();
  const input = document.getElementById("server-url") as HTMLInputElement | null;
  if (!input) return;

  try {
    const normalizedValue = await setServerBaseUrl(input.value);
    input.value = normalizedValue;
    await notifyBackground();
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
  await notifyBackground();
  setStatus(`Reset to ${DEFAULT_SERVER_BASE_URL}`, "success");
}

document.getElementById("server-form")?.addEventListener("submit", (event) => {
  saveServerUrl(event).catch(console.error);
});

document.getElementById("reset-defaults")?.addEventListener("click", () => {
  resetDefaults().catch(console.error);
});

loadForm().catch(console.error);
