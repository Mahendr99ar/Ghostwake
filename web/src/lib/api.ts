// Thin client for the GhostWake API. In dev Vite proxies /api; in production
// VITE_API_URL points at the Render service.

const BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");

export type Severity = "info" | "watch" | "high" | "critical";
export type Status = "open" | "escalated" | "dismissed";

export interface AlertSummary {
  id: string;
  kind: string;
  category: "enforcement" | "safety";
  severity: Severity;
  status: Status;
  mmsi: string | null;
  detection_id: string | null;
  start: string;
  end: string;
  lat: number;
  lon: number;
  summary: string;
  score: number;
}

export interface AlertDetail extends AlertSummary {
  contributions: { reason: string; points: number }[];
  evidence: Record<string, any>;
  lineage: {
    run_id: string;
    pipeline_version: string;
    rule: string;
    thresholds: Record<string, number>;
    sources: Record<string, any>[];
    cleaning: Record<string, number>;
  };
  reviews: { action: string; analyst: string; note: string; ts: string }[];
  vessel?: { mmsi: string; name: string; flag: string; type: string; length_m: number; risk: number } | null;
  detection?: {
    id: string; scene_id: string; ts: string; lat: number; lon: number;
    length_m: number; confidence: number; model_version: string;
  } | null;
}

export interface Track { mmsi: string; path: [number, number][]; t: number[] }
export interface Detection {
  id: string; scene_id: string; ts: string; lat: number; lon: number;
  length_m: number; confidence: number; matched_mmsi: string | null;
}
export interface Vessel {
  mmsi: string; name: string; flag: string; type: string; length_m: number;
  risk: number; last_seen: string; lat: number; lon: number;
}
export interface Health {
  ok: boolean; version: string; copilot: "llm" | "offline"; open_alerts: number;
  data_through: string | null;
  last_run: null | {
    id: string; finished_at: string; source: string;
    counts: Record<string, number>; cleaning: Record<string, number>;
    params: { seed: number; scenario_start: string };
  };
}
export interface CopilotAnswer {
  answer: string;
  mode: "llm" | "offline" | "guardrail";
  tool_calls: { tool: string; args: Record<string, unknown> }[];
  refused: boolean;
  checks: { unverified_numbers: string[] };
  note?: string;
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`${r.status} on ${path}`);
  return r.json();
}

async function post<T>(path: string, body: unknown, headers: Record<string, string> = {}): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail ?? `Request failed (${r.status})`);
  return data as T;
}

export const api = {
  health: () => get<Health>("/api/health"),
  meta: () => get<{ aoi: Record<string, number>; zones: GeoJSON.FeatureCollection }>("/api/meta"),
  alerts: () => get<AlertSummary[]>("/api/alerts"),
  alert: (id: string) => get<AlertDetail>(`/api/alerts/${id}`),
  tracks: () => get<{ t0: string | null; tracks: Track[] }>("/api/tracks"),
  detections: () => get<Detection[]>("/api/detections"),
  vessels: () => get<Vessel[]>("/api/vessels"),
  chip: (id: string) => get<{ size: number; pixels: number[][]; synthetic: boolean }>(`/api/detections/${id}/chip`),
  review: (id: string, action: "escalate" | "dismiss" | "reopen", note: string, token: string, analyst: string) =>
    post<AlertSummary>(`/api/alerts/${id}/review`, { action, note }, {
      Authorization: `Bearer ${token}`,
      "X-Analyst": analyst || "analyst",
    }),
  ask: (question: string, alert_id?: string) => post<CopilotAnswer>("/api/copilot", { question, alert_id }),
  reportUrl: (id: string) => `${BASE}/api/alerts/${id}/report`,
  streamUrl: () => `${BASE}/api/stream`,
};
