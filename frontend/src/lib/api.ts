import { getSession, signOut } from "next-auth/react";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

type FetchOptions = RequestInit & {
  token?: string;
};

let isRefreshing = false;

/**
 * On 401, try refreshing the NextAuth session (which triggers the JWT callback
 * and calls /auth/refresh on the backend). If refresh succeeds, retry the
 * original request with the new token. If it fails, sign out.
 */
async function handleUnauthorized(
  path: string,
  options: FetchOptions,
  buildHeaders: (token?: string) => HeadersInit,
): Promise<Response | null> {
  // Avoid concurrent refresh attempts
  if (isRefreshing) return null;
  isRefreshing = true;

  try {
    // Force NextAuth to refresh the session (triggers jwt callback → refreshAccessToken)
    const newSession = await getSession();
    if (newSession?.access_token && !newSession.error) {
      // Retry the original request with the refreshed token
      const { headers: _, token: _t, ...rest } = options;
      const retryResponse = await fetch(`${API_BASE_URL}${path}`, {
        headers: buildHeaders(newSession.access_token),
        ...rest,
      });
      if (retryResponse.status !== 401) {
        return retryResponse;
      }
    }
  } catch {
    // Refresh failed
  } finally {
    isRefreshing = false;
  }

  // Refresh failed or retry still 401 — sign out
  signOut({ callbackUrl: "/login" });
  throw new Error("Session expirée");
}

export async function apiFetch<T>(
  path: string,
  options: FetchOptions = {}
): Promise<T> {
  const { token, headers, ...rest } = options;

  const buildHeaders = (t?: string): HeadersInit => ({
    "Content-Type": "application/json",
    ...(t ? { Authorization: `Bearer ${t}` } : {}),
    ...headers,
  });

  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: buildHeaders(token),
    ...rest,
  });

  if (response.status === 401) {
    const retryResponse = await handleUnauthorized(path, options, buildHeaders);
    if (retryResponse) {
      if (!retryResponse.ok) {
        const errorData = await retryResponse.json().catch(() => null);
        const detail = errorData?.detail;
        throw new Error(
          typeof detail === "string" ? detail : `Erreur ${retryResponse.status}`,
        );
      }
      if (retryResponse.status === 204) return undefined as T;
      return retryResponse.json() as Promise<T>;
    }
  }

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    const detail = errorData?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: { msg?: string }) => d.msg || d).join(". ")
          : `Erreur ${response.status}`,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

/**
 * Fetch brut avec gestion du 401. Pour les cas où apiFetch ne convient pas
 * (FormData upload, streaming SSE). Ne parse pas le JSON automatiquement.
 */
export async function authFetch(
  path: string,
  options: FetchOptions = {}
): Promise<Response> {
  const { token, headers, ...rest } = options;

  const buildHeaders = (t?: string): HeadersInit => ({
    ...(t ? { Authorization: `Bearer ${t}` } : {}),
    ...headers,
  });

  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: buildHeaders(token),
    ...rest,
  });

  if (response.status === 401) {
    const retryResponse = await handleUnauthorized(path, options, buildHeaders);
    if (retryResponse) return retryResponse;
  }

  return response;
}
