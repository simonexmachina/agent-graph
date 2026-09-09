/**
 * Toolbar icon indicator for the active observation.
 *
 * Chrome action badges require text, so draw compact overlays over the Ag
 * icon instead. This preserves the icon while keeping current page state
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

export const BOOKMARK_INDICATOR_COLOR = "#000000";

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

export function getActionTitle(state: ObservationState, bookmarked: boolean): string {
  const observationTitle = getActionIndicator(state)?.title;
  if (bookmarked && observationTitle) return `${observationTitle}; bookmarked page`;
  if (bookmarked) return "AgentGraph: bookmarked page";
  return observationTitle ?? "AgentGraph";
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

function drawBookmarkIndicator(context: OffscreenCanvasRenderingContext2D, size: number): void {
  const inset = Math.max(1, Math.round(size * 0.06));
  const width = Math.max(3, Math.round(size * 0.22));
  const height = Math.max(4, Math.round(size * 0.31));
  const notch = Math.max(1, Math.round(height * 0.22));

  context.beginPath();
  context.moveTo(inset, inset);
  context.lineTo(inset + width, inset);
  context.lineTo(inset + width, inset + height);
  context.lineTo(inset + width / 2, inset + height - notch);
  context.lineTo(inset, inset + height);
  context.closePath();
  context.fillStyle = BOOKMARK_INDICATOR_COLOR;
  context.fill();
}

function drawActionIcon(icon: ImageBitmap, size: number, indicator: ActionIndicator | null, bookmarked: boolean): ImageData {
  if (indicator === null && !bookmarked) {
    const canvas = new OffscreenCanvas(size, size);
    const context = canvas.getContext("2d");
    if (context === null) throw new Error("Could not create action icon canvas");
    context.drawImage(icon, 0, 0, size, size);
    return context.getImageData(0, 0, size, size);
  }

  const canvas = new OffscreenCanvas(size, size);
  const context = canvas.getContext("2d");
  if (context === null) throw new Error("Could not create action icon canvas");
  context.drawImage(icon, 0, 0, size, size);
  if (bookmarked) drawBookmarkIndicator(context, size);
  if (indicator !== null) {
    const radius = Math.max(2, Math.round(size * 0.16));
    const inset = Math.max(1, Math.round(size * 0.06));
    const center = size - radius - inset;
    context.beginPath();
    context.arc(center, center, radius + 1, 0, Math.PI * 2);
    context.fillStyle = "#ffffff";
    context.fill();
    context.beginPath();
    context.arc(center, center, radius, 0, Math.PI * 2);
    context.fillStyle = indicator.color;
    context.fill();
  }
  return context.getImageData(0, 0, size, size);
}

export async function updateActionIndicator(state: ObservationState, bookmarked = false): Promise<void> {
  const indicator = getActionIndicator(state);
  const version = ++updateVersion;

  if (indicator === null && !bookmarked) {
    await chrome.action.setIcon({ path: BASE_ICON_PATHS });
    if (version === updateVersion) await chrome.action.setTitle({ title: getActionTitle(state, bookmarked) });
    return;
  }

  try {
    const baseIcons = await getBaseIcons();
    if (version !== updateVersion) return;
    const imageData = Object.fromEntries(
      Object.entries(baseIcons).map(([size, icon]) => [
        Number(size),
        drawActionIcon(icon, Number(size), indicator, bookmarked),
      ]),
    );
    await chrome.action.setIcon({ imageData });
    if (version === updateVersion) await chrome.action.setTitle({ title: getActionTitle(state, bookmarked) });
  } catch (error: unknown) {
    console.error("Could not update AgentGraph action indicator", error);
  }
}
