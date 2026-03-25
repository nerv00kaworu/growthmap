/**
 * Performance tests for Zustand selectors.
 *
 * Validates that granular selectors:
 *  1. Return the correct slices of state.
 *  2. Produce stable references when unrelated state changes (useShallow).
 *  3. Reduce per-component subscription count vs raw useStore.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useStore } from "@/stores/useStore";
import {
  useMindMapData,
  useHeaderData,
  useHeaderActions,
  useNodePanelData,
  useNodePanelActions,
} from "@/stores/selectors";

/* ────── helpers ────── */

/** Reset store to initial state between tests */
function resetStore() {
  useStore.setState({
    projects: [],
    currentProject: null,
    rootNode: null,
    selectedNodeId: null,
    selectedNode: null,
    loading: false,
    error: null,
    errorStatus: null,
    errorRetryable: false,
    expandSuggestions: null,
    expandTargetNodeId: null,
    deepenResult: null,
    aiLoading: false,
  });
}

beforeEach(resetStore);

/* ────── useMindMapData ────── */

describe("useMindMapData", () => {
  it("returns rootNode, selectedNodeId, and selectNode", () => {
    const { result } = renderHook(() => useMindMapData());
    expect(result.current).toHaveProperty("rootNode");
    expect(result.current).toHaveProperty("selectedNodeId");
    expect(result.current).toHaveProperty("selectNode");
    expect(Object.keys(result.current)).toHaveLength(3);
  });

  it("produces stable reference when unrelated state changes", () => {
    const { result } = renderHook(() => useMindMapData());
    const first = result.current;

    // Mutate an unrelated field (loading)
    act(() => useStore.setState({ loading: true }));
    const second = result.current;

    // useShallow should keep the same object reference
    expect(first).toBe(second);
  });

  it("produces new reference when relevant state changes", () => {
    const { result } = renderHook(() => useMindMapData());
    const first = result.current;

    act(() => useStore.setState({ selectedNodeId: "node-42" }));
    const second = result.current;

    expect(second.selectedNodeId).toBe("node-42");
    expect(first).not.toBe(second);
  });
});

/* ────── useHeaderData ────── */

describe("useHeaderData", () => {
  it("returns the 6 expected fields", () => {
    const { result } = renderHook(() => useHeaderData());
    const keys = Object.keys(result.current).sort();
    expect(keys).toEqual([
      "currentProject",
      "error",
      "errorRetryable",
      "errorStatus",
      "loading",
      "projects",
    ]);
  });

  it("is stable when AI state changes", () => {
    const { result } = renderHook(() => useHeaderData());
    const first = result.current;

    act(() => useStore.setState({ aiLoading: true }));
    expect(result.current).toBe(first);
  });

  it("updates when error changes", () => {
    const { result } = renderHook(() => useHeaderData());
    const first = result.current;

    act(() => useStore.setState({ error: "boom", errorStatus: 500, errorRetryable: false }));
    expect(result.current).not.toBe(first);
    expect(result.current.error).toBe("boom");
    expect(result.current.errorStatus).toBe(500);
  });
});

/* ────── useHeaderActions ────── */

describe("useHeaderActions", () => {
  it("returns 4 action functions", () => {
    const { result } = renderHook(() => useHeaderActions());
    expect(typeof result.current.loadProjects).toBe("function");
    expect(typeof result.current.selectProject).toBe("function");
    expect(typeof result.current.createProject).toBe("function");
    expect(typeof result.current.dismissError).toBe("function");
    expect(Object.keys(result.current)).toHaveLength(4);
  });

  it("action references are stable across state changes", () => {
    const { result } = renderHook(() => useHeaderActions());
    const first = result.current;

    act(() => useStore.setState({ loading: true, error: "oops" }));
    // Actions are top-level Zustand functions — they never change identity
    expect(result.current).toBe(first);
  });
});

/* ────── useNodePanelData ────── */

describe("useNodePanelData", () => {
  it("returns selectedNode, rootNode, expandSuggestions, deepenResult, aiLoading", () => {
    const { result } = renderHook(() => useNodePanelData());
    const keys = Object.keys(result.current).sort();
    expect(keys).toEqual([
      "aiLoading",
      "deepenResult",
      "expandSuggestions",
      "rootNode",
      "selectedNode",
    ]);
  });

  it("is stable when header-only fields change", () => {
    const { result } = renderHook(() => useNodePanelData());
    const first = result.current;

    act(() => useStore.setState({ loading: true, error: "x" }));
    expect(result.current).toBe(first);
  });

  it("updates when aiLoading toggles", () => {
    const { result } = renderHook(() => useNodePanelData());
    const first = result.current;

    act(() => useStore.setState({ aiLoading: true }));
    expect(result.current).not.toBe(first);
    expect(result.current.aiLoading).toBe(true);
  });
});

/* ────── useNodePanelActions ────── */

describe("useNodePanelActions", () => {
  it("returns 11 action functions", () => {
    const { result } = renderHook(() => useNodePanelActions());
    const actual = result.current;
    const actualKeys = Object.keys(actual);
    const expected = [
      "addChildNode",
      "updateNode",
      "deleteNode",
      "promoteMainlineChild",
      "expandNode",
      "deepenNode",
      "acceptSuggestion",
      "acceptAllSuggestions",
      "acceptDeepen",
      "dismissAI",
      "refreshTree",
    ];
    expect(actualKeys.sort()).toEqual(expected.sort());
    for (const key of actualKeys) {
      expect(typeof actual[key as keyof typeof actual]).toBe("function");
    }
  });

  it("action references are stable across any state change", () => {
    const { result } = renderHook(() => useNodePanelActions());
    const first = result.current;

    act(() => useStore.setState({ aiLoading: true, rootNode: null, error: "err" }));
    expect(result.current).toBe(first);
  });
});

/* ────── Cross-slice isolation ────── */

describe("Cross-slice isolation", () => {
  it("MindMap selector ignores header state changes", () => {
    const { result } = renderHook(() => useMindMapData());
    const first = result.current;

    act(() =>
      useStore.setState({
        loading: true,
        error: "fail",
        errorStatus: 503,
        projects: [{ id: "p1", name: "P", root_node_id: "r", created_at: "", updated_at: "" }],
      })
    );
    expect(result.current).toBe(first);
  });

  it("Header selector ignores mind-map state changes", () => {
    const { result } = renderHook(() => useHeaderData());
    const first = result.current;

    act(() => useStore.setState({ selectedNodeId: "n1", aiLoading: true }));
    expect(result.current).toBe(first);
  });

  it("NodePanel data selector ignores header state changes", () => {
    const { result } = renderHook(() => useNodePanelData());
    const first = result.current;

    act(() => useStore.setState({ loading: true, error: "oops", errorRetryable: true }));
    expect(result.current).toBe(first);
  });
});
