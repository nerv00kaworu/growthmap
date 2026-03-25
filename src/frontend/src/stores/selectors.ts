/**
 * Granular Zustand selectors for minimizing re-renders.
 *
 * Instead of pulling many individual fields from the store (each creating
 * a subscription), these selectors group related state into shallow-compared
 * slices.  Components import the hook they need, and only re-render when
 * the fields inside that slice actually change.
 */
import { useStore } from "./useStore";
import { useShallow } from "zustand/react/shallow";

/* ───── MindMap ───── */

/** Only the data MindMap needs: tree + selection id + selectNode action */
export function useMindMapData() {
  return useStore(
    useShallow((s) => ({
      rootNode: s.rootNode,
      selectedNodeId: s.selectedNodeId,
      selectNode: s.selectNode,
    }))
  );
}

/* ───── Page / Header ───── */

/** Top-bar needs: project list, current project, loading, error state */
export function useHeaderData() {
  return useStore(
    useShallow((s) => ({
      projects: s.projects,
      currentProject: s.currentProject,
      loading: s.loading,
      error: s.error,
      errorStatus: s.errorStatus,
      errorRetryable: s.errorRetryable,
    }))
  );
}

/** Top-bar actions — stable references, never change */
export function useHeaderActions() {
  return useStore(
    useShallow((s) => ({
      loadProjects: s.loadProjects,
      selectProject: s.selectProject,
      createProject: s.createProject,
      dismissError: s.dismissError,
    }))
  );
}

/* ───── NodePanel ───── */

/** Node detail panel data slice */
export function useNodePanelData() {
  return useStore(
    useShallow((s) => ({
      selectedNode: s.selectedNode,
      rootNode: s.rootNode,
      expandSuggestions: s.expandSuggestions,
      deepenResult: s.deepenResult,
      aiLoading: s.aiLoading,
    }))
  );
}

/** Node panel actions — stable references */
export function useNodePanelActions() {
  return useStore(
    useShallow((s) => ({
      addChildNode: s.addChildNode,
      updateNode: s.updateNode,
      deleteNode: s.deleteNode,
      promoteMainlineChild: s.promoteMainlineChild,
      expandNode: s.expandNode,
      deepenNode: s.deepenNode,
      acceptSuggestion: s.acceptSuggestion,
      acceptAllSuggestions: s.acceptAllSuggestions,
      acceptDeepen: s.acceptDeepen,
      dismissAI: s.dismissAI,
      refreshTree: s.refreshTree,
    }))
  );
}
