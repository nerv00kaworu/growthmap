import type { CanonicalDelta } from "./api";
import { SSEParser, parseCanonicalWake, parseReadyFrame } from "./sse-parser";

export type LiveOwner = { projectId: string; branchId: string | null; loadedRevision: number; epoch: number };
type StreamResponse = { ok: boolean; status: number; body?: ReadableStream<Uint8Array> | null };
export type LiveSyncDependencies = {
  getOwner: () => LiveOwner | null;
  getRevision: (projectId: string) => Promise<{ revision: number }>;
  getChanges: (projectId: string, since: number) => Promise<CanonicalDelta>;
  applyDelta: (owner: LiveOwner, delta: CanonicalDelta) => boolean;
  refresh: (owner: LiveOwner) => Promise<void>;
  isUnsafe: () => boolean;
  notice: (visible: boolean) => void;
  fetch: (url: string, init: RequestInit) => Promise<StreamResponse>;
  document: Pick<Document, "visibilityState" | "addEventListener" | "removeEventListener">;
  window: Pick<Window, "addEventListener" | "removeEventListener">;
  setInterval?: (fn: () => void, ms: number) => number;
  clearInterval?: (id: number) => void;
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
};

/** One owner, one scalar/delta pair. SSE is an invalidation hint, never data. */
export class LiveSyncController {
  private stopped = true;
  private running = false;
  private trailing = false;
  private generation = 0;
  private timer: number | undefined;
  private abort?: AbortController;
  private sleepAbort?: AbortController;
  private reader?: ReadableStreamDefaultReader<Uint8Array>;
  constructor(private readonly d: LiveSyncDependencies) {}
  mount(): void {
    if (!this.stopped) return;
    this.stopped = false; this.generation++;
    this.d.window.addEventListener("focus", this.onFocus);
    this.d.document.addEventListener("visibilitychange", this.onVisibility);
    this.timer = this.d.setInterval?.(() => { if (this.d.document.visibilityState === "visible") void this.wake(); }, 45_000);
    void this.stream(); // deliberately caught inside stream
  }
  unmount(): void {
    if (this.stopped) return;
    this.stopped = true; this.generation++; this.trailing = false;
    if (this.timer !== undefined) this.d.clearInterval?.(this.timer);
    this.d.window.removeEventListener("focus", this.onFocus);
    this.d.document.removeEventListener("visibilitychange", this.onVisibility);
    this.abort?.abort(); this.sleepAbort?.abort(); void this.reader?.cancel().catch(() => undefined);
  }
  async manualRefresh(): Promise<void> {
    const owner=this.d.getOwner(); if (!owner) return;
    try {
      await this.d.refresh(owner);
      // A refresh is expected to advance loadedRevision.  The captured epoch is
      // the authority fence; allowing only a monotonic revision advance avoids
      // turning a legitimate readback into a false stale-result warning.
      if (this.sameRefreshOwner(owner)) this.d.notice(false);
    }
    catch { if (this.sameRefreshOwner(owner)) this.d.notice(true); }
  }
  private sameRefreshOwner(owner: LiveOwner): boolean {
    const now=this.d.getOwner();
    return !!now && now.projectId===owner.projectId && now.branchId===owner.branchId &&
      now.epoch===owner.epoch && now.loadedRevision>=owner.loadedRevision;
  }
  wake = async (): Promise<void> => {
    if (this.stopped || this.d.document.visibilityState !== "visible") return;
    if (this.running) { this.trailing = true; return; }
    this.running = true;
    const generation = this.generation;
    try {
      const owner = this.d.getOwner();
      if (!owner || owner.branchId !== null || this.d.isUnsafe()) { if (owner) this.d.notice(true); return; }
      // Read owner immediately before each request, never from a render closure.
      const scalar = await this.d.getRevision(owner.projectId);
      const current = this.d.getOwner();
      if (!this.current(generation, owner, current) || scalar.revision <= owner.loadedRevision) return;
      if (this.d.isUnsafe()) { this.d.notice(true); return; }
      const delta = await this.d.getChanges(owner.projectId, owner.loadedRevision);
      const settle = this.d.getOwner();
      if (!this.current(generation, owner, settle) || this.d.isUnsafe()) { this.d.notice(true); return; }
      if (!this.d.applyDelta(owner, delta)) { this.d.notice(true); return; }
      this.d.notice(false);
    } catch { if (!this.stopped && generation === this.generation) this.d.notice(true); }
    finally {
      this.running = false;
      if (!this.stopped && this.trailing) { this.trailing = false; void this.wake(); }
    }
  };
  private current(g: number, captured: LiveOwner, now: LiveOwner | null): boolean {
    return !this.stopped && g === this.generation && !!now && now.projectId === captured.projectId && now.branchId === captured.branchId && now.loadedRevision === captured.loadedRevision && now.epoch === captured.epoch;
  }
  private onFocus = (): void => { void this.wake(); };
  private onVisibility = (): void => { if (this.d.document.visibilityState === "visible") void this.wake(); };
  private async stream(): Promise<void> {
    let backoff = 1_000;
    while (!this.stopped) {
      this.abort = new AbortController();
      try {
        const response = await this.d.fetch("/api/changes/stream", { cache: "no-store", signal: this.abort.signal });
        if (response.status === 401 || response.status === 403 || this.stopped) return;
        if (!response.ok || !response.body) throw new Error("stream unavailable");
        backoff = 1_000;
        const reader = this.reader = response.body.getReader(); const decoder = new TextDecoder(); const parser = new SSEParser();
        try {
          while (!this.stopped) {
            const { value, done } = await reader.read();
            const text = value ? decoder.decode(value, { stream: !done }) : "";
            for (const event of parser.push(text)) {
              const wake = event.event === "canonical-change" ? parseCanonicalWake(event.data) : null;
              const owner = this.d.getOwner();
              if (wake && owner && wake.project_id === owner.projectId) void this.wake();
              if (event.event === "ready" && parseReadyFrame(event.data)) void this.wake();
            }
            if (done) { for (const event of parser.push(decoder.decode())) { const wake=event.event === "canonical-change" ? parseCanonicalWake(event.data) : null; if (wake && wake.project_id === this.d.getOwner()?.projectId) void this.wake(); if (event.event === "ready" && parseReadyFrame(event.data)) void this.wake(); } break; }
          }
        } finally { if (this.reader === reader) this.reader = undefined; reader.releaseLock(); }
      } catch { if (this.stopped) return; }
      if (this.stopped) return;
      this.sleepAbort = new AbortController();
      try { await (this.d.sleep?.(backoff, this.sleepAbort.signal) ?? Promise.resolve()); } catch { return; }
      backoff = Math.min(backoff * 2, 30_000);
    }
  }
}
