/**
 * Toolbar icon indicator for the active observation.
 *
 * Chrome action badges require text, so draw a small status dot over the Ag
 * icon instead. This preserves the icon while keeping the current state
 * visible without opening the popup.
 */

type ObservationState =
  | "not_matched"
  | "waiting"
  | "sending"
  | "sent"
  | "failed"
  | "canceled";

export interface ActionIndicator {
  color: string;
  title: string;
}

const BASE_ICON_PATHS = {
  16: "assets/icon-16.png",
  32: "assets/icon-32.png",
};

const INDICATORS: Partial<Record<ObservationState, ActionIndicator>> = {
  waiting: { color: "#2563eb", title: "AgentGraph: observing page" },
  sending: { color: "#f59e0b", title: "AgentGraph: sending observation" },
  sent: { color: "#16a34a", title: "AgentGraph: observation sent" },
};

let baseIconsPromise: Promise<Record<number, ImageBitmap>> | null = null;
let updateVersion = 0;

export function getActionIndicator(state: ObservationState): ActionIndicator | null {
  return INDICATORS[state] ?? null;
}

async function loadBaseIcons(): Promise<Record<number, ImageBitmap>> {
  const loaded = await Promise.all(
    Object.entries(BASE_ICON_PATHS).map(async ([size, path]) => {
      const response = await fetch(chrome.runtime.getURL(path));
      if (!response.ok) throw new Error(`Could not load action icon: ${path}`);
      return [Number(size), await createImageBitmap(await response.blob())] as const;
    }),
  );
  return Object.fromEntries(loaded);
}

async function getBaseIcons(): Promise<Record<number, ImageBitmap>> {
  baseIconsPromise ??= loadBaseIcons();
  return await baseIconsPromise;
}

function drawIndicator(icon: ImageBitmap, size: number, color: string): ImageData {
  const canvas = new OffscreenCanvas(size, size);
  const context = canvas.getContext("2d");
  if (context === null) throw new Error("Could not create action icon canvas");

  context.drawImage(icon, 0, 0, size, size);
  const radius = Math.max(2, Math.round(size * 0.16));
  const inset = Math.max(1, Math.round(size * 0.06));
  const center = size - radius - inset;

  context.beginPath();
  context.arc(center, center, radius + 1, 0, Math.PI * 2);
  context.fillStyle = "#ffffff";
  context.fill();
  context.beginPath();
  context.arc(center, center, radius, 0, Math.PI * 2);
  context.fillStyle = color;
  context.fill();
  return context.getImageData(0, 0, size, size);
}

export async function updateActionIndicator(state: ObservationState): Promise<void> {
  const indicator = getActionIndicator(state);
  const version = ++updateVersion;

  if (indicator === null) {
    await chrome.action.setIcon({ path: BASE_ICON_PATHS });
    if (version === updateVersion) await chrome.action.setTitle({ title: "AgentGraph" });
    return;
  }

  try {
    const baseIcons = await getBaseIcons();
    if (version !== updateVersion) return;
    const imageData = Object.fromEntries(
      Object.entries(baseIcons).map(([size, icon]) => [Number(size), drawIndicator(icon, Number(size), indicator.color)]),
    );
    await chrome.action.setIcon({ imageData });
    if (version === updateVersion) await chrome.action.setTitle({ title: indicator.title });
  } catch (error: unknown) {
    console.error("Could not update AgentGraph action indicator", error);
  }
}
