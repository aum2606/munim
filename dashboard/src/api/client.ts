// The only place that calls fetch. The access token lives in memory (not localStorage), so page
// scripts can't steal a long-lived credential; the refresh token is an httpOnly cookie that
// JavaScript never sees.
export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

export interface User {
  id: string
  email: string
  name: string
  role: 'owner' | 'staff'
  is_active: boolean
}

export interface Tenant {
  id: string
  name: string
  business_type: string
  timezone: string
}

export interface Me {
  user: User
  tenant: Tenant
}

interface Token {
  access_token: string
}

let accessToken: string | null = null
let refreshing: Promise<boolean> | null = null

export function setAccessToken(token: string | null): void {
  accessToken = token
}

/** Trade the refresh cookie for a new access token. One refresh at a time, shared by callers. */
export function refreshSession(): Promise<boolean> {
  refreshing ??= (async () => {
    const response = await fetch('/api/v1/auth/refresh', {
      method: 'POST',
      credentials: 'same-origin',
    })
    if (!response.ok) {
      accessToken = null
      return false
    }
    accessToken = ((await response.json()) as Token).access_token
    return true
  })().finally(() => {
    refreshing = null
  })
  return refreshing
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
}

export async function api<T>(
  path: string,
  { method = 'GET', body }: RequestOptions = {},
  canRetry = true,
): Promise<T> {
  // FormData (file uploads) is sent as is so the browser sets the multipart boundary itself.
  const isForm = body instanceof FormData
  const response = await fetch(`/api/v1${path}`, {
    method,
    credentials: 'same-origin',
    headers: {
      ...(body === undefined || isForm ? {} : { 'Content-Type': 'application/json' }),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  })

  // Access token expired: refresh once and replay. Auth endpoints report their own 401s.
  if (
    response.status === 401 &&
    canRetry &&
    !path.startsWith('/auth/') &&
    (await refreshSession())
  ) {
    return api<T>(path, { method, body }, false)
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      error?: { code?: string; message?: string }
    } | null
    throw new ApiError(
      response.status,
      payload?.error?.code ?? 'error',
      payload?.error?.message ?? response.statusText,
    )
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T)
}

/** Fetch a file with the signed-in user's token (a plain link cannot send it) and open it. */
export async function openPdf(path: string): Promise<void> {
  if (!accessToken) await refreshSession()
  const response = await fetch(`/api/v1${path}`, {
    credentials: 'same-origin',
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  })
  if (!response.ok) throw new ApiError(response.status, 'download_failed', response.statusText)
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  window.open(url, '_blank', 'noopener')
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
