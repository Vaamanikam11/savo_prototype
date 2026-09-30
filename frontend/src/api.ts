export type Turn = { index: number; role: "interviewer" | "participant"; text: string };
export type Evidence = { quote: string; turn_index: number | null; start: number | null; end: number | null };
export type Signal = {
  dimension: string;
  score: number | null;
  status: "scored" | "insufficient_evidence";
  rationale: string;
  evidence: Evidence[];
  dropped_quotes: number;
};
export type Session = {
  id: string;
  status: "active" | "complete" | "scored";
  framework_id: string;
  turns: Turn[];
  signals: Signal[];
  next_question: string | null;
  done: boolean;
};
export type Dimension = { key: string; label: string; definition: string; anchors: Record<string, string> };
export type Framework = { id: string; title: string; max_turns: number; dimensions: Dimension[] };

export type Config = { access_code_required: boolean; scorer: string };

async function call<T>(path: string, init?: RequestInit, code?: string): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...(code ? { "X-Access-Code": code } : {}) },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail ?? `Request failed (${res.status})`);
  }
  return res.json();
}

export const api = {
  config: () => call<Config>("/config"),
  framework: () => call<Framework>("/framework"),
  start: (code?: string) => call<Session>("/sessions", { method: "POST" }, code),
  answer: (id: string, text: string) =>
    call<Session>(`/sessions/${id}/turns`, { method: "POST", body: JSON.stringify({ text }) }),
  finish: (id: string) => call<Session>(`/sessions/${id}/finish`, { method: "POST" }),
  score: (id: string) => call<Session>(`/sessions/${id}/score`, { method: "POST" }),
};
