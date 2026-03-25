export const RETRYABLE_API_STATUSES = new Set([408, 429, 500, 502, 503]);

export function isRetryableStatus(status: number): boolean {
  return RETRYABLE_API_STATUSES.has(status);
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public retryable: boolean = false
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function createApiError(status: number, message: string): ApiError {
  return new ApiError(status, message, isRetryableStatus(status));
}

export interface ErrorDetails {
  message: string;
  status: number | null;
  retryable: boolean;
}

export function getErrorDetails(error: unknown): ErrorDetails {
  if (error instanceof ApiError) {
    return {
      message: error.message,
      status: error.status,
      retryable: error.retryable,
    };
  }

  if (error instanceof Error) {
    return {
      message: error.message,
      status: null,
      retryable: false,
    };
  }

  return {
    message: "發生未知錯誤。",
    status: null,
    retryable: false,
  };
}
