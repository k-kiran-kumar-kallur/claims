import { render, screen } from "@testing-library/react";
import { ActivityLog } from "../ActivityLog";
import { fmtDuration, fmtRelative } from "../common";
import { formatEvent, logToText, nodeName, toLogLines } from "../runLog";

const ev = (id: number, event: string, data: Record<string, any> = {}) => ({ id, event, data });

describe("run log formatting", () => {
  it("humanizes node names and acronyms", () => {
    expect(nodeName("intake_agent")).toBe("Intake agent");
    expect(nodeName("rtw_extractor")).toBe("RTW extractor");
    expect(nodeName("hitl_signoff")).toBe("Human review: signoff");
    expect(nodeName(undefined)).toBe("Workflow");
  });

  it("maps events to levels and readable messages", () => {
    expect(formatEvent(ev(1, "run_failed", { error: "boom" }))).toMatchObject({ level: "error", message: "Run failed", detail: "boom" });
    expect(formatEvent(ev(2, "awaiting_review", { checkpoint: "HITL-0", title: "Confirm baseline" }))).toMatchObject({ level: "review", message: "Waiting for review at HITL-0 - Confirm baseline" });
    expect(formatEvent(ev(3, "retrying", { node: "intake_agent", attempt: 2, delay_s: 4, error: "429" }))).toMatchObject({ level: "warning", detail: "429" });
    expect(formatEvent(ev(4, "tool_called", { node: "intake_agent", tool: "ingest", pages: 20, documents: 3 })).detail).toBe("pages: 20 · documents: 3");
  });

  it("pairs node_started with node_completed to compute durations", () => {
    const lines = toLogLines([
      ev(1, "node_started", { node: "intake_agent", ts: "2026-01-01T10:00:00.000Z" }),
      ev(2, "node_completed", { node: "intake_agent", ts: "2026-01-01T10:00:02.500Z", output: { documents: 4 } }),
    ]);
    expect(lines[1]).toMatchObject({ level: "success", message: "Intake agent finished", detail: "documents: 4", durationMs: 2500 });
    expect(logToText(lines).split("\n")).toHaveLength(2);
  });

  it("renders key events and hides debug lines by default", () => {
    render(<ActivityLog events={[ev(1, "node_started", { node: "intake_agent" }), ev(2, "run_completed", { total_tokens: 1200 })]} />);
    expect(screen.getByText("Run completed")).toBeInTheDocument();
    expect(screen.queryByText(/Ingesting/)).not.toBeInTheDocument();
    expect(screen.getByText(/Showing 1 of 2 events/)).toBeInTheDocument();
  });
});

describe("time helpers", () => {
  const now = Date.parse("2026-01-01T12:00:00Z");
  it("formats relative times", () => {
    expect(fmtRelative("2026-01-01T11:59:50Z", now)).toBe("just now");
    expect(fmtRelative("2026-01-01T11:55:00Z", now)).toBe("5 min ago");
    expect(fmtRelative("2026-01-01T09:00:00Z", now)).toBe("3 h ago");
    expect(fmtRelative("2026-01-01T15:00:00Z", now)).toBe("in 3 h");
  });
  it("formats durations", () => {
    expect(fmtDuration(450)).toBe("450 ms");
    expect(fmtDuration(2500)).toBe("2.5 s");
    expect(fmtDuration(125_000)).toBe("2m 5s");
  });
});
