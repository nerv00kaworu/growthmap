export interface NodeHistoryViewState<H, R> {
  selectionKey: string;
  history: H[];
  readbacks: R[];
  show: boolean;
  loading: boolean;
  error: string | null;
  traceUnavailable: boolean;
}

export function freshNodeHistoryView<H, R>(selectionKey: string): NodeHistoryViewState<H, R> {
  return {selectionKey,history:[],readbacks:[],show:false,loading:false,error:null,traceUnavailable:false};
}

export function visibleNodeHistoryView<H, R>(state: NodeHistoryViewState<H, R>, currentSelectionKey: string): NodeHistoryViewState<H, R> {
  // Props can change one commit before the cleanup effect runs. Never expose
  // data tagged for the previous selection during that render.
  return state.selectionKey === currentSelectionKey ? state : freshNodeHistoryView<H, R>(currentSelectionKey);
}

export interface NodeHistoryLoadCallbacks<H, A> {
  onHistory: (history: H) => void;
  onActivity: (activity: A) => void;
  onUnavailable: () => void;
  onError: (error: unknown) => void;
  onSettled: () => void;
}

export class NodeHistoryRequestCoordinator {
  private generation = 0;
  private selectedKey: string;

  constructor(selectedKey: string) { this.selectedKey = selectedKey; }

  select(selectedKey: string): void {
    this.selectedKey = selectedKey;
    this.generation += 1;
  }

  begin(selectedKey: string): () => boolean {
    const generation = ++this.generation;
    return () => this.generation === generation && this.selectedKey === selectedKey;
  }
}

export async function loadNodeHistory<H, A>(
  coordinator: NodeHistoryRequestCoordinator,
  selectedKey: string,
  getHistory: () => Promise<H>,
  getActivity: () => Promise<A>,
  callbacks: NodeHistoryLoadCallbacks<H, A>,
): Promise<void> {
  const isCurrent = coordinator.begin(selectedKey);
  try {
    const history = await getHistory();
    if (!isCurrent()) return;
    callbacks.onHistory(history);
    try {
      const activity = await getActivity();
      if (!isCurrent()) return;
      callbacks.onActivity(activity);
    } catch (error: unknown) {
      if (!isCurrent()) return;
      const status = typeof error === "object" && error !== null && "status" in error ? (error as { status?: unknown }).status : undefined;
      if (status === 401 || status === 403) callbacks.onUnavailable();
      else callbacks.onError(error);
    }
  } catch (error: unknown) {
    if (isCurrent()) callbacks.onError(error);
  } finally {
    if (isCurrent()) callbacks.onSettled();
  }
}
