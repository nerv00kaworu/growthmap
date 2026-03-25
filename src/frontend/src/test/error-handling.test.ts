import { fireEvent, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { ApiError, createApiError, isRetryableStatus } from "@/lib/errors";

function ThrowError() {
  throw new Error("Boom");
}

let shouldThrowOnRetryTest = false;

function RetryableThrower() {
  if (shouldThrowOnRetryTest) {
    throw new Error("Retry me");
  }

  return createElement("div", null, "Recovered content");
}

describe("ApiError", () => {
  it("stores status, message, and retryable flag", () => {
    const error = new ApiError(503, "Service unavailable", true);

    expect(error.name).toBe("ApiError");
    expect(error.status).toBe(503);
    expect(error.message).toBe("Service unavailable");
    expect(error.retryable).toBe(true);
  });

  it("detects retryable statuses", () => {
    expect(isRetryableStatus(408)).toBe(true);
    expect(isRetryableStatus(429)).toBe(true);
    expect(isRetryableStatus(500)).toBe(true);
    expect(isRetryableStatus(502)).toBe(true);
    expect(isRetryableStatus(503)).toBe(true);
    expect(isRetryableStatus(404)).toBe(false);
    expect(createApiError(500, "Server error").retryable).toBe(true);
    expect(createApiError(400, "Bad request").retryable).toBe(false);
  });
});

describe("ErrorBoundary", () => {
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    shouldThrowOnRetryTest = false;
    consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
  });

  it("renders children normally", () => {
    render(createElement(ErrorBoundary, null, createElement("div", null, "Healthy content")));

    expect(screen.getByText("Healthy content")).toBeInTheDocument();
  });

  it("shows fallback UI when a child throws", () => {
    render(createElement(ErrorBoundary, null, createElement(ThrowError)));

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("這個區塊暫時無法顯示")).toBeInTheDocument();
    expect(screen.getByText("Boom")).toBeInTheDocument();
  });

  it("resets the boundary when retry is clicked", () => {
    shouldThrowOnRetryTest = true;

    render(createElement(ErrorBoundary, null, createElement(RetryableThrower)));

    expect(screen.getByRole("button", { name: "重試" })).toBeInTheDocument();

    shouldThrowOnRetryTest = false;

    fireEvent.click(screen.getByRole("button", { name: "重試" }));

    expect(screen.getByText("Recovered content")).toBeInTheDocument();
  });
});
