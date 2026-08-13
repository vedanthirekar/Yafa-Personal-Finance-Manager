/**
 * The single place this app talks to the API.
 *
 * Everything goes through `request()`, so auth headers, error shaping, and
 * token refresh are handled once rather than at each call site.
 *
 * Tokens live in localStorage. That is readable by any script on the page, so
 * it is a real XSS exposure -- the correct production answer is an httpOnly
 * cookie set by the server. It is called out here rather than left implicit;
 * access tokens are short-lived (30 min) which limits the blast radius.
 */

import type {
  CategorizationQuality,
  CategorizeResponse,
  CategoryBreakdownItem,
  ForecastResponse,
  TokenResponse,
  Transaction,
  TransactionPage,
  User,
  VoiceResult,
} from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const ACCESS_KEY = "yafa.access_token";
const REFRESH_KEY = "yafa.refresh_token";

export const tokens = {
  get access() {
    if (typeof window === "undefined") return null;
    return window.localStorage.getItem(ACCESS_KEY);
  },
  get refresh() {
    if (typeof window === "undefined") return null;
    return window.localStorage.getItem(REFRESH_KEY);
  },
  set(access: string, refresh: string) {
    window.localStorage.setItem(ACCESS_KEY, access);
    window.localStorage.setItem(REFRESH_KEY, refresh);
  },
  clear() {
    window.localStorage.removeItem(ACCESS_KEY);
    window.localStorage.removeItem(REFRESH_KEY);
  },
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Prevents a burst of 401s from firing N parallel refreshes. */
let refreshInFlight: Promise<boolean> | null = null;

async function refreshAccessToken(): Promise<boolean> {
  const refresh_token = tokens.refresh;
  if (!refresh_token) return false;

  refreshInFlight ??= (async () => {
    try {
      const res = await fetch(`${API_URL}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token }),
      });
      if (!res.ok) return false;
      const data: TokenResponse = await res.json();
      tokens.set(data.access_token, data.refresh_token);
      return true;
    } catch {
      return false;
    } finally {
      // Cleared on the next tick so callers awaiting this promise all observe
      // the same result before a new refresh can start.
      setTimeout(() => (refreshInFlight = null), 0);
    }
  })();

  return refreshInFlight;
}

interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Internal: stops a failed refresh from recursing forever. */
  _retry?: boolean;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, _retry, headers, ...rest } = options;

  const isFormData = body instanceof FormData;
  const res = await fetch(`${API_URL}${path}`, {
    ...rest,
    headers: {
      // FormData must set its own Content-Type so the multipart boundary is
      // included; setting it manually produces an unparseable request.
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(tokens.access ? { Authorization: `Bearer ${tokens.access}` } : {}),
      ...headers,
    },
    body: isFormData ? body : body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401 && !_retry) {
    if (await refreshAccessToken()) {
      return request<T>(path, { ...options, _retry: true });
    }
    tokens.clear();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new ApiError(401, "Session expired");
  }

  if (!res.ok) {
    // FastAPI puts the message in `detail`, which is a string for HTTPException
    // and an array of field errors for a validation failure.
    let message = res.statusText;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") message = data.detail;
      else if (Array.isArray(data.detail)) {
        message = data.detail.map((d: { msg: string }) => d.msg).join(", ");
      }
    } catch {
      /* non-JSON error body; statusText is the best we have */
    }
    throw new ApiError(res.status, message);
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

// ---------------------------------------------------------------------------
// auth
// ---------------------------------------------------------------------------

export const api = {
  async login(username: string, password: string) {
    const data = await request<TokenResponse>("/auth/login", {
      method: "POST",
      body: { username, password },
    });
    tokens.set(data.access_token, data.refresh_token);
    return data;
  },

  async register(payload: {
    username: string;
    email: string;
    name: string;
    password: string;
  }) {
    const data = await request<TokenResponse>("/auth/register", {
      method: "POST",
      body: payload,
    });
    tokens.set(data.access_token, data.refresh_token);
    return data;
  },

  async demoLogin() {
    const data = await request<TokenResponse>("/auth/demo-login", { method: "POST" });
    tokens.set(data.access_token, data.refresh_token);
    return data;
  },

  logout() {
    tokens.clear();
  },

  me: () => request<User>("/auth/me"),

  // -------------------------------------------------------------------------
  // transactions
  // -------------------------------------------------------------------------

  transactions: (params: {
    limit?: number;
    offset?: number;
    category?: string;
    search?: string;
    start_date?: string;
    end_date?: string;
  } = {}) => {
    const query = new URLSearchParams(
      Object.entries(params)
        .filter(([, v]) => v !== undefined && v !== "")
        .map(([k, v]) => [k, String(v)]),
    );
    return request<TransactionPage>(`/transactions?${query}`);
  },

  createTransaction: (payload: {
    date: string;
    description: string;
    category: string;
    amount: string;
    currency?: string;
    merchant?: string | null;
  }) => request<Transaction>("/transactions", { method: "POST", body: payload }),

  updateTransaction: (id: number, payload: Record<string, unknown>) =>
    request<Transaction>(`/transactions/${id}`, { method: "PATCH", body: payload }),

  /** Distinct from a PATCH: this also feeds the correction back as training
   *  data and can pin the merchant's category. */
  correctCategory: (id: number, category: string, remember_for_merchant = true) =>
    request<Transaction>(`/transactions/${id}/correct-category`, {
      method: "POST",
      body: { category, remember_for_merchant },
    }),

  deleteTransaction: (id: number) =>
    request<void>(`/transactions/${id}`, { method: "DELETE" }),

  categoryBreakdown: () =>
    request<CategoryBreakdownItem[]>("/transactions/stats/by-category"),

  categorizationQuality: () =>
    request<CategorizationQuality>("/transactions/stats/categorization-quality"),

  // -------------------------------------------------------------------------
  // ai
  // -------------------------------------------------------------------------

  categorize: (text: string) =>
    request<CategorizeResponse>("/categorize", { method: "POST", body: { text } }),

  transcribe: (audio: Blob, filename = "recording.webm") => {
    const form = new FormData();
    form.append("file", audio, filename);
    return request<VoiceResult>("/voice/transcribe", { method: "POST", body: form });
  },

  confirmVoice: (result: VoiceResult) =>
    request<Transaction>("/voice/confirm", { method: "POST", body: result }),

  forecast: (steps = 6) => request<ForecastResponse>(`/forecast/me?steps=${steps}`),
};

/** WebSocket URL for live voice capture.
 *
 *  The token rides in the query string because browsers cannot set an
 *  Authorization header on a WebSocket handshake. It therefore lands in server
 *  access logs -- which is why the backend only accepts short-lived access
 *  tokens here, never refresh tokens.
 */
export function voiceSocketUrl(): string {
  const base = API_URL.replace(/^http/, "ws");
  return `${base}/ws/voice?token=${encodeURIComponent(tokens.access ?? "")}`;
}
