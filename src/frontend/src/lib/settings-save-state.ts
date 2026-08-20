export type SettingsSavePhase = "idle" | "metadata" | "secret" | "refresh" | "selection" | "selection_committed" | "saved" | "selection_retry" | "metadata_failed" | "secret_failed";

export interface SettingsSaveState {
  phase: SettingsSavePhase;
  providerId?: string;
  metadataSaved: boolean;
  secretSaved: boolean;
  selectionRevision?: number;
}

export type SettingsSaveEvent =
  | { type: "START" }
  | { type: "METADATA_OK"; providerId: string }
  | { type: "METADATA_FAIL" }
  | { type: "SECRET_OK" }
  | { type: "SECRET_FAIL" }
  | { type: "REFRESH_OK"; selectionRevision: number }
  | { type: "SELECTION_COMMITTED"; selectionRevision: number }
  | { type: "READBACK_OK" }
  | { type: "READBACK_FAIL" }
  | { type: "SELECTION_RETRY"; selectionRevision: number };

export const initialSettingsSaveState: SettingsSaveState = { phase: "idle", metadataSaved: false, secretSaved: false };

/** Pure split-save state machine. A committed PUT can never regress to retry. */
export function reduceSettingsSave(state: SettingsSaveState, event: SettingsSaveEvent): SettingsSaveState {
  switch (event.type) {
    case "START": return { phase: "metadata", metadataSaved: false, secretSaved: false };
    case "METADATA_OK": return { ...state, phase: "secret", providerId: event.providerId, metadataSaved: true };
    case "METADATA_FAIL": return { ...state, phase: "metadata_failed" };
    case "SECRET_OK": return { ...state, phase: "refresh", secretSaved: true };
    case "SECRET_FAIL": return { ...state, phase: "secret_failed" };
    case "REFRESH_OK": return { ...state, phase: "selection", selectionRevision: event.selectionRevision };
    case "SELECTION_RETRY": return state.phase === "selection_committed" || state.phase === "saved" ? state : { ...state, phase: "selection_retry", selectionRevision: event.selectionRevision };
    case "SELECTION_COMMITTED": return { ...state, phase: "selection_committed", selectionRevision: event.selectionRevision };
    case "READBACK_OK": return { ...state, phase: "saved" };
    case "READBACK_FAIL": return state.phase === "selection_committed" ? state : state;
  }
}
