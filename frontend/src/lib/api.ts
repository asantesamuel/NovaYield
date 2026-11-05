// Host-only browser cookies cannot be read across localhost and 127.0.0.1.
// Follow the page host for local development unless deployment supplies a URL.
const DEFAULT_API_BASE_URL = `${window.location.protocol}//${window.location.hostname}:8000/api/v1`

/** Base URL for cookie-authenticated FastAPI calls. */
export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL?.trim() || DEFAULT_API_BASE_URL
).replace(/\/+$/, '')
