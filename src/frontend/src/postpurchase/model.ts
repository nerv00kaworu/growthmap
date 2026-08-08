import { PostPurchaseState, POST_PURCHASE_STATES } from "./catalog";

const publicSnapshotBrand: unique symbol = Symbol("PublicPostPurchaseSnapshot");
export interface PublicPostPurchaseSnapshot {
  readonly state: PostPurchaseState;
  readonly correlationId?: string;
  readonly keyAvailable: boolean;
  readonly [publicSnapshotBrand]: true;
}
export interface ActivationKeyLoader { load(options: { signal: AbortSignal }): Promise<string> }
export type EntryKind = "retry" | "recovery" | "devices" | "refund" | "support";
export type EntryHandler = () => void | Promise<void>;
export type EntryHandlers = Readonly<Partial<Record<EntryKind, EntryHandler>>>;
export type SecretClearLifecycle = (clear: () => void) => () => void;

export const ENTRY_ORDER: readonly EntryKind[] = ["retry", "recovery", "devices", "refund", "support"];
export const ALLOWED_ENTRIES: Readonly<Record<PostPurchaseState, readonly EntryKind[]>> = {
  success: ["recovery", "devices", "support"], "delivery-pending": ["retry", "recovery", "support"], recovered: ["devices", "support"],
  refunded: ["refund", "support"], disputed: ["refund", "support"], outage: ["retry", "recovery", "support"],
};

export function sanitizeCorrelationId(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(trimmed) ? trimmed : null;
}

/**
 * Strict projection of observable own keys. Proxies can lie, so every reflection failure rejects.
 * No value read, getter, or toJSON invocation occurs before data-descriptor validation.
 */
export function projectPublicPostPurchaseSnapshot(input: unknown): PublicPostPurchaseSnapshot {
  if (!input || typeof input !== "object" || Array.isArray(input)) throw new TypeError("invalid post-purchase snapshot");
  try {
    const keys = Reflect.ownKeys(input); // exactly one captured observable-key snapshot
    const allowed = new Set(["state", "correlationId", "keyAvailable"]);
    const captured: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
    for (const key of keys) {
      if (typeof key !== "string" || !allowed.has(key)) throw new TypeError("unknown post-purchase snapshot field");
      const descriptor = Object.getOwnPropertyDescriptor(input, key);
      if (!descriptor || !("value" in descriptor) || descriptor.get || descriptor.set) throw new TypeError("invalid post-purchase snapshot descriptor");
      captured[key] = descriptor.value;
    }
    if (!("state" in captured) || !("keyAvailable" in captured)) throw new TypeError("missing post-purchase snapshot field");
    const state = captured.state;
    const keyAvailable = captured.keyAvailable;
    const rawCorrelationId = captured.correlationId;
    if (typeof state !== "string" || !(POST_PURCHASE_STATES as readonly string[]).includes(state)) throw new TypeError("invalid post-purchase state");
    if (typeof keyAvailable !== "boolean") throw new TypeError("invalid key availability");
    const correlationId = rawCorrelationId === undefined ? undefined : sanitizeCorrelationId(rawCorrelationId);
    if (rawCorrelationId !== undefined && correlationId === null) throw new TypeError("invalid correlation id");
    const projected = { state: state as PostPurchaseState, keyAvailable, ...(correlationId === undefined ? {} : { correlationId }) };
    Object.defineProperty(projected, publicSnapshotBrand, { value: true, enumerable: false });
    return Object.freeze(projected) as PublicPostPurchaseSnapshot;
  } catch (error) {
    if (error instanceof TypeError && /^unknown|^invalid|^missing/.test(error.message)) throw error;
    throw new TypeError("uninspectable post-purchase snapshot");
  }
}

export function canRequestKey(snapshot: PublicPostPurchaseSnapshot): boolean {
  return snapshot.keyAvailable && (snapshot.state === "success" || snapshot.state === "recovered");
}
export function subscribeDocumentHidden(clear: () => void): () => void {
  if (typeof document === "undefined") return () => undefined;
  const onVisibility = () => { if (document.visibilityState === "hidden") clear(); };
  document.addEventListener("visibilitychange", onVisibility);
  return () => document.removeEventListener("visibilitychange", onVisibility);
}

/** Mounted/generation fence shared by reveal and deferred clipboard operations. */
export class OperationFence {
  #generation = 0;
  #controller: AbortController | null = null;
  #mounted = false;
  mount(): void { this.#mounted = true; }
  unmount(): void { this.#mounted = false; this.invalidate(); }
  beginReveal(): { generation: number; signal: AbortSignal } | null {
    if (!this.#mounted) return null;
    this.#controller?.abort();
    this.#controller = new AbortController();
    return { generation: ++this.#generation, signal: this.#controller.signal };
  }
  capture(): number | null { return this.#mounted ? this.#generation : null; }
  isCurrent(generation: number): boolean { return this.#mounted && generation === this.#generation; }
  invalidate(): void { this.#generation += 1; this.#controller?.abort(); this.#controller = null; }
}

export class EphemeralSecret {
  #value: string | null = null;
  set(value: string): void { this.#value = value; }
  get(): string | null { return this.#value; }
  clear(): void { this.#value = null; }
  dispose(): void { this.clear(); }
}
