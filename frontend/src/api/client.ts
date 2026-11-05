/** Cookie-authenticated API transport shared by the frontend feature modules. */

import { API_BASE_URL } from '../lib/api';
const CSRF_COOKIE_NAME = 'nova_yield_csrf';
export const SESSION_EXPIRED_EVENT = 'nova-yield:session-expired';

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(
    message: string,
    status: number,
    code?: string,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

function readCookie(name: string): string | null {
  const prefix = `${name}=`;
  const value = document.cookie.split('; ').find((part) => part.startsWith(prefix));
  return value ? decodeURIComponent(value.slice(prefix.length)) : null;
}

let csrfBootstrap: Promise<string> | null = null;

async function getCsrfToken(): Promise<string> {
  const existing = readCookie(CSRF_COOKIE_NAME);
  if (existing) return existing;

  // A safe GET lets starlette-csrf set a readable, signed cookie. Share an
  // in-flight request so simultaneous mutations do not bootstrap repeatedly.
  csrfBootstrap ??= (async () => {
    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}/auth/csrf`, { credentials: 'include' });
    } catch {
      throw new ApiError('Could not connect to NovaYield. Please retry.', 503, 'NETWORK_ERROR');
    }
    if (!response.ok) {
      throw new ApiError('Could not prepare a secure request. Please retry.', response.status);
    }
    const token = readCookie(CSRF_COOKIE_NAME);
    if (!token) {
      throw new ApiError(
        'Could not read the security cookie. Use the same site for the frontend and API.',
        403,
        'CSRF_COOKIE_UNAVAILABLE',
      );
    }
    return token;
  })();

  try {
    return await csrfBootstrap;
  } finally {
    csrfBootstrap = null;
  }
}

function errorMessage(data: unknown, fallback: string): string {
  if (!data || typeof data !== 'object') return fallback;
  const record = data as Record<string, unknown>;
  if (typeof record.detail === 'string') return record.detail;
  if (typeof record.message === 'string') return record.message;
  if (Array.isArray(record.detail)) {
    const messages = record.detail
      .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
      .map((item) => {
        const field = Array.isArray(item.loc) ? item.loc.at(-1) : null;
        const message = typeof item.msg === 'string' ? item.msg : 'Invalid value';
        return typeof field === 'string' ? `${field}: ${message}` : message;
      });
    if (messages.length) return messages.join('; ');
  }
  return fallback;
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body !== undefined && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }
  const method = (options.method || 'GET').toUpperCase();
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    headers.set('X-CSRF-Token', await getCsrfToken());
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${endpoint}`, {
      ...options,
      headers,
      credentials: 'include',
    });
  } catch {
    throw new ApiError('Could not connect to NovaYield. Please retry.', 503, 'NETWORK_ERROR');
  }

  const data = response.headers.get('content-type')?.includes('application/json')
    ? await response.json() as unknown
    : undefined;
  if (!response.ok) {
    if (response.status === 401 && !endpoint.startsWith('/auth/')) {
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
    }
    const code = data && typeof data === 'object'
      ? (data as Record<string, unknown>).code
      : undefined;
    throw new ApiError(
      errorMessage(data, response.statusText || 'The request failed.'),
      response.status,
      typeof code === 'string' ? code : undefined,
    );
  }
  return data as T;
}

export const api = {
  get: <T>(endpoint: string) => request<T>(endpoint),
  post: <T>(endpoint: string, body?: unknown) => request<T>(endpoint, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  }),
  patch: <T>(endpoint: string, body: unknown) => request<T>(endpoint, {
    method: 'PATCH',
    body: JSON.stringify(body),
  }),
  put: <T>(endpoint: string, body: unknown) => request<T>(endpoint, {
    method: 'PUT',
    body: JSON.stringify(body),
  }),
  delete: <T>(endpoint: string) => request<T>(endpoint, { method: 'DELETE' }),
};
