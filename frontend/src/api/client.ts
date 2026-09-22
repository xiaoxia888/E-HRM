export class ApiError extends Error {
  readonly status: number
  readonly details: unknown

  constructor(message: string, status: number, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.details = details
  }
}

export async function apiRequest<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      Accept: 'application/json',
      ...options?.headers,
    },
  })
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const message =
      payload && typeof payload.message === 'string'
        ? payload.message
        : payload && typeof payload.detail === 'string'
          ? payload.detail
          : `请求失败（HTTP ${response.status}）`
    throw new ApiError(message, response.status, payload?.details)
  }
  return payload as T
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) {
    return error.message
  }
  return '操作失败，请稍后重试'
}
