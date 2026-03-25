import React, { type ErrorInfo, type ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = {
    hasError: false,
    error: null,
  };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return {
      hasError: true,
      error,
    };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error("ErrorBoundary caught an error", error, errorInfo);
  }

  private resetBoundary = (): void => {
    this.setState({ hasError: false, error: null });
  };

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div className="flex h-full items-center justify-center p-6">
          <div role="alert" className="surface-panel w-full max-w-xl rounded-2xl p-6 text-[var(--text-primary)]">
            <div className="eyebrow-label">Unexpected error</div>
            <h2 className="mt-2 text-lg font-semibold text-[var(--text-primary)]">這個區塊暫時無法顯示</h2>
            <p className="mt-2 text-sm text-[var(--text-muted)]">
              發生未預期的渲染錯誤。你可以先重試，如果問題持續再重新整理頁面。
            </p>
            <div className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-3 text-xs text-[var(--text-faint)] break-words">
              {this.state.error?.message || "Unknown error"}
            </div>
            <div className="mt-5 flex justify-end">
              <button
                type="button"
                onClick={this.resetBoundary}
                className="surface-subtle rounded-lg px-4 py-2 text-sm text-[var(--text-primary)] hover:text-[var(--text-primary)]"
              >
                重試
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
