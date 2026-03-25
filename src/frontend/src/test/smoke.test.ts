/**
 * Smoke tests to verify vitest setup, mocks, and basic imports.
 */
import { describe, it, expect } from "vitest";

describe("Vitest setup", () => {
  it("should run a basic assertion", () => {
    expect(1 + 1).toBe(2);
  });

  it("should have ResizeObserver available", () => {
    expect(globalThis.ResizeObserver).toBeDefined();
    const observer = new ResizeObserver(() => {});
    observer.observe(document.createElement("div"));
    observer.disconnect();
  });

  it("should have DOMMatrixReadOnly available", () => {
    expect(globalThis.DOMMatrixReadOnly).toBeDefined();
    const matrix = new DOMMatrixReadOnly();
    expect(matrix).toBeDefined();
  });

  it("should have matchMedia available", () => {
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    expect(mql).toBeDefined();
    expect(mql.matches).toBe(false);
  });

  it("should have IntersectionObserver available", () => {
    expect(globalThis.IntersectionObserver).toBeDefined();
  });
});

describe("Path alias @/", () => {
  it("should resolve @/lib/types", async () => {
    const types = await import("@/lib/types");
    expect(types.MATURITY_LABELS).toBeDefined();
    expect(typeof types.MATURITY_LABELS).toBe("object");
    expect(types.MATURITY_LABELS.seed).toContain("種子");
  });
});
