export type ApiErrorCategory =
  | "AUTHENTICATION"
  | "AUTHORIZATION"
  | "VALIDATION"
  | "NOT_FOUND"
  | "CONFLICT"
  | "DEPENDENCY"
  | "RATE_LIMITED"
  | "REQUEST"
  | "INTERNAL";

export class ApiError extends Error {
  readonly category: ApiErrorCategory;
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly retryable: boolean;

  constructor({
    category,
    code,
    message,
    requestId,
    retryable,
    status,
  }: {
    category: ApiErrorCategory;
    code: string;
    message: string;
    requestId: string | null;
    retryable: boolean;
    status: number;
  }) {
    super(message);
    this.name = "ApiError";
    this.category = category;
    this.code = code;
    this.requestId = requestId;
    this.retryable = retryable;
    this.status = status;
  }
}

export function categoryForStatus(status: number): ApiErrorCategory {
  if (status === 401) return "AUTHENTICATION";
  if (status === 403) return "AUTHORIZATION";
  if (status === 404) return "NOT_FOUND";
  if (status === 409) return "CONFLICT";
  if (status === 413 || status === 415 || status === 422) return "VALIDATION";
  if (status === 429) return "RATE_LIMITED";
  if (status === 500) return "INTERNAL";
  if (status >= 500) return "DEPENDENCY";
  return "REQUEST";
}

export function safeMessageForStatus(status: number): string {
  if (status === 401) return "Authentication was not accepted.";
  if (status === 403) return "This credential is not authorized for the operation.";
  if (status === 404) return "The requested verification resource was not found.";
  if (status === 409) return "The verification session changed before this operation completed.";
  if (status === 413 || status === 415 || status === 422) return "The request or media could not be accepted.";
  if (status === 429) return "Too many requests. Please try again shortly.";
  if (status >= 500) return "The verification service is temporarily unavailable.";
  return "The verification request could not be completed.";
}

export function networkError(): ApiError {
  return new ApiError({
    category: "DEPENDENCY",
    code: "NETWORK_ERROR",
    message: "The verification service could not be reached.",
    requestId: null,
    retryable: true,
    status: 0,
  });
}
