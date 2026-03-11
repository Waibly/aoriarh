import { signOut } from "next-auth/react";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

type FetchOptions = RequestInit & {
  token?: string;
};

function handle401(response: Response): void {
  if (response.status === 401) {
    signOut({ callbackUrl: "/login" });
    throw new Error("Session expirée");
  }
}

export async function apiFetch<T>(
  path: string,
  options: FetchOptions = {}
): Promise<T> {
  const { token, headers, ...rest } = options;

  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    ...rest,
  });

  handle401(response);

  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`);
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

  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    ...rest,
  });

  handle401(response);

  return response;
}
