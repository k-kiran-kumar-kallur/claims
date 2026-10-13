import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getAccessToken, refreshAccessToken } from "../api/client";

export interface RunEvent {
  id: number;
  event: string;
  data: Record<string, any>;
}

const INVALIDATE: Record<string, string[][]> = {
  intake_agent: [["claim"], ["documents"]],
  organization_agent: [["timeline"], ["documents"]],
  classify_document: [["documents"]],
  validation_agent: [["facts"]],
  guideline_agent: [["findings"], ["flags"]],
  report_agent: [["summaries"]],
  chronology_agent: [["chronology"]],
  record_keeping: [["decisions"], ["reports"]],
};

/** Server-sent events over fetch (so the bearer token can be sent); reconnects with Last-Event-ID. */
export function useRunEvents(runId?: string | null, claimId?: string) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const lastId = useRef(0);
  const qc = useQueryClient();

  useEffect(() => {
    if (!runId) return;
    setEvents([]);
    lastId.current = 0;
    const ctrl = new AbortController();
    let stopped = false;

    const handle = (ev: RunEvent) => {
      setEvents((prev) => [...prev.slice(-300), ev]);
      if (["node_completed", "awaiting_review", "awaiting_documents", "run_completed", "run_failed", "run_cancelled", "run_resumed", "retrying"].includes(ev.event)) {
        qc.invalidateQueries({ queryKey: ["claim", claimId] });
        qc.invalidateQueries({ queryKey: ["runs", claimId] });
        qc.invalidateQueries({ queryKey: ["reviews"] });
        (INVALIDATE[ev.data?.node] || []).forEach((k) => qc.invalidateQueries({ queryKey: [...k, claimId] }));
        if (ev.event === "run_completed" || ev.event === "awaiting_review") qc.invalidateQueries({ queryKey: ["dashboard", claimId] });
      }
    };

    const connect = async (attempt = 0): Promise<void> => {
      if (stopped) return;
      try {
        let token = getAccessToken();
        let r = await fetch(`/api/v1/runs/${runId}/events`, {
          headers: { Authorization: `Bearer ${token}`, "Last-Event-ID": String(lastId.current), Accept: "text/event-stream" },
          signal: ctrl.signal,
        });
        if (r.status === 401) {
          token = await refreshAccessToken();
          r = await fetch(`/api/v1/runs/${runId}/events`, {
            headers: { Authorization: `Bearer ${token}`, "Last-Event-ID": String(lastId.current) },
            signal: ctrl.signal,
          });
        }
        if (!r.ok || !r.body) throw new Error(`SSE ${r.status}`);
        setConnected(true);
        const reader = r.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          const parts = buf.split(/\r?\n\r?\n/);
          buf = parts.pop() || "";
          for (const part of parts) {
            let id = 0, event = "message", data = "";
            for (const line of part.split(/\r?\n/)) {
              if (line.startsWith("id:")) id = Number(line.slice(3).trim());
              else if (line.startsWith("event:")) event = line.slice(6).trim();
              else if (line.startsWith("data:")) data += line.slice(5).trim();
            }
            if (event === "end") {
              stopped = true;
              return;
            }
            if (!data || event === "ping") continue;
            if (id) lastId.current = id;
            try {
              handle({ id, event, data: JSON.parse(data) });
            } catch {
              /* ignore malformed */
            }
          }
        }
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
      } finally {
        setConnected(false);
      }
      if (!stopped) setTimeout(() => connect(attempt + 1), Math.min(1000 * 2 ** attempt, 15000));
    };
    connect();
    return () => {
      stopped = true;
      ctrl.abort();
    };
  }, [runId, claimId, qc]);

  return { events, connected };
}
