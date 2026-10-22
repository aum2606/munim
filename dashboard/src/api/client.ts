export interface Tokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
}
export interface User {
  id: string;
  tenant_id: string;
  name: string;
  email: string;
  role: "owner" | "staff" | "admin";
}
export interface Registration {
  business_name: string;
  business_type: string;
  name: string;
  email: string;
  password: string;
}
let tokens: Tokens | null = null;
let onSessionLost = () => {};
export function setTokens(value: Tokens | null) {
  tokens = value;
}
export function hasSession() {
  return tokens !== null;
}
export function setSessionLost(handler: () => void) {
  onSessionLost = handler;
}
let refreshing: Promise<void> | null = null;
async function request<T>(
  path: string,
  init: RequestInit = {},
  retry = true,
  format: "json" | "blob" = "json",
): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers: {
      ...(init.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...(tokens ? { Authorization: `Bearer ${tokens.access_token}` } : {}),
      ...init.headers,
    },
  });
  if (
    response.status === 401 &&
    tokens &&
    retry &&
    !path.startsWith("/auth/")
  ) {
    if (!refreshing)
      refreshing = request<Tokens>(
        "/auth/refresh",
        {
          method: "POST",
          body: JSON.stringify({ refresh_token: tokens.refresh_token }),
        },
        false,
      )
        .then(setTokens)
        .catch((error: unknown) => {
          setTokens(null);
          onSessionLost();
          throw error;
        })
        .finally(() => {
          refreshing = null;
        });
    await refreshing;
    return request<T>(path, init, false, format);
  }
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  if (response.status === 204) return undefined as T;
  if (format === "blob") return (await response.blob()) as T;
  return response.json() as Promise<T>;
}
export const api = {
  login: (email: string, password: string) =>
    request<Tokens>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  register: (registration: Registration) =>
    request<Tokens>("/auth/register", {
      method: "POST",
      body: JSON.stringify(registration),
    }),
  me: () => request<User>("/me"),
  logout: async () => {
    try {
      if (tokens)
        await request<void>("/auth/logout", {
          method: "POST",
          body: JSON.stringify({ refresh_token: tokens.refresh_token }),
        });
    } finally {
      setTokens(null);
    }
  },
};

export function authenticatedRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  return request<T>(path, init);
}
export function authenticatedDownload(path: string): Promise<Blob> {
  return request<Blob>(path, {}, true, "blob");
}
