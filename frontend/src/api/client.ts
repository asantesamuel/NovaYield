// frontend/src/api/client.ts

// Fallback to localhost if VITE_API_BASE_URL isn't set, per the README
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  
  const headers = new Headers(options.headers || {});
  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const config: RequestInit = {
    ...options,
    headers,
    credentials: 'include', // Essential for cookie-based auth later
  };

  try {
    const response = await fetch(url, config);
    
    // Check if response is JSON before parsing
    const contentType = response.headers.get('content-type');
    const isJson = contentType && contentType.includes('application/json');
    const data = isJson ? await response.json() : null;

    if (!response.ok) {
      // FastAPI standard error shape is usually { detail: "..." }
      const errorMessage = data?.detail || data?.message || response.statusText || 'An unknown error occurred';
      const errorCode = data?.code || data?.error_code;
      
      throw new ApiError(errorMessage, response.status, errorCode);
    }

    return data as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    
    // Handle network failures (e.g., backend is down)
    if (error instanceof TypeError && error.message === 'Failed to fetch') {
      throw new ApiError('Network error: Could not connect to the server.', 503, 'NETWORK_ERROR');
    }
    
    throw new ApiError('An unexpected error occurred.', 500, 'UNKNOWN_ERROR');
  }
}

export const api = {
  get: <T>(endpoint: string, options?: RequestInit) => 
    request<T>(endpoint, { ...options, method: 'GET' }),
    
  post: <T>(endpoint: string, body: unknown, options?: RequestInit) => 
    request<T>(endpoint, { ...options, method: 'POST', body: JSON.stringify(body) }),
    
  put: <T>(endpoint: string, body: unknown, options?: RequestInit) => 
    request<T>(endpoint, { ...options, method: 'PUT', body: JSON.stringify(body) }),
    
  delete: <T>(endpoint: string, options?: RequestInit) => 
    request<T>(endpoint, { ...options, method: 'DELETE' }),
};