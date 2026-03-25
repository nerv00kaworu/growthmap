/**
 * Vitest global setup — mocks required for React Flow and browser APIs.
 */
import "@testing-library/jest-dom/vitest";

// React Flow requires ResizeObserver which jsdom doesn't provide
class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverMock as unknown as typeof ResizeObserver;

// React Flow uses DOMMatrixReadOnly for transforms
class DOMMatrixReadOnlyMock {
  m22: number;
  constructor(transform?: string) {
    const scale = transform?.match(/scale\(([^)]+)\)/)?.[1];
    this.m22 = scale ? parseFloat(scale) : 1;
  }
  get a() { return this.m22; }
  get b() { return 0; }
  get c() { return 0; }
  get d() { return this.m22; }
  get e() { return 0; }
  get f() { return 0; }
  inverse() { return new DOMMatrixReadOnlyMock(); }
}
globalThis.DOMMatrixReadOnly = DOMMatrixReadOnlyMock as unknown as typeof DOMMatrixReadOnly;

// Mock window.matchMedia (used by various UI components)
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

// Mock IntersectionObserver (lazy-loaded components)
class IntersectionObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.IntersectionObserver = IntersectionObserverMock as unknown as typeof IntersectionObserver;
