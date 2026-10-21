const DEFAULT_API_BASE_URL = 'http://localhost:8000/api/v1'

/** Base URL for future FastAPI calls; no API requests are made by the scaffold. */
export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL?.trim() || DEFAULT_API_BASE_URL
).replace(/\/+$/, '')
