export interface ObservationStatus {
  url: string;
  matches: boolean;
  state: "not_matched" | "waiting" | "sending" | "sent" | "failed" | "canceled";
  threshold_ms: number;
  started_at?: number;
  fires_at?: number;
  sent_at?: number;
  http_status?: number;
  error?: string;
}

export async function refreshPendingObservation(
  current: ObservationStatus | null,
  load: () => Promise<ObservationStatus | null>,
): Promise<ObservationStatus | null> {
  if (current?.state !== "waiting" && current?.state !== "sending") return current;
  return await load();
}
