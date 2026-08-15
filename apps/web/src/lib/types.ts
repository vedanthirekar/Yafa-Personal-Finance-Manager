/**
 * Domain types mirroring the FastAPI response models.
 *
 * These are hand-written rather than generated. The generated
 * `openapi-typescript` output is accurate but close to unreadable
 * (deeply-nested `paths[...]["get"]["responses"][200]` lookups), and this
 * codebase is meant to stay legible. To check for drift against the real
 * schema, run `npm run check:api-types` -- it regenerates into a scratch file
 * and diffs the operation list, so a backend change that isn't reflected here
 * shows up rather than silently breaking at runtime.
 */

export type TransactionSource = "voice" | "manual" | "import" | "demo_seed";

export type ExtractionMethod = "regex" | "words" | "llm" | "none";

export interface User {
  id: number;
  username: string;
  email: string;
  name: string;
  currency: string;
  is_demo: boolean;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  username: string;
  name: string;
}

export interface Transaction {
  id: number;
  date: string;
  description: string;
  category: string;
  /** Serialized as a string: these are Postgres NUMERIC values, and routing
   *  money through a JS number would reintroduce the float rounding the
   *  backend deliberately avoids. Parse only for display. */
  amount: string;
  currency: string;
  source: TransactionSource;
  merchant: string | null;
  raw_transcript: string | null;
  created_at: string;
  /** null when the row was entered manually and never went through the model. */
  confidence: number | null;
  was_auto_categorized: boolean;
}

export interface TransactionPage {
  items: Transaction[];
  total: number;
  limit: number;
  offset: number;
}

export interface CategoryScore {
  category: string;
  confidence: number;
}

export interface CategorizeResponse {
  category: string | null;
  confidence: number;
  alternatives: CategoryScore[];
}

/** What the server proposes after transcribing. Nothing is saved yet. */
export interface VoiceResult {
  transcript: string;
  description: string;
  amount: string | null;
  currency: string;
  merchant: string | null;
  date: string;
  category: string | null;
  confidence: number;
  extraction_method: ExtractionMethod;
}

/**
 * What we send to POST /voice/confirm once the user approves.
 *
 * `category` is by then whatever the user settled on, so the model's original
 * guess is echoed back separately. Without it the server can't tell a
 * correction from an acceptance, and the categorizer would score 100% forever.
 */
export interface VoiceConfirmPayload extends VoiceResult {
  predicted_category: string | null;
  predicted_confidence: number;
}

export interface CategoryBreakdownItem {
  category: string;
  total_amount: string;
  transaction_count: number;
  pct_of_total: number;
}

export interface ForecastPoint {
  date: string;
  amount: string;
  lower: string | null;
  upper: string | null;
}

export interface ForecastSeries {
  category: string | null;
  history: ForecastPoint[];
  forecast: ForecastPoint[];
  /** e.g. "ARIMA(5, 1, 0)" or "mean-baseline". Shown in the chart footnote. */
  model: string;
  /** false when there wasn't enough history to fit -- the UI says so instead
   *  of drawing a flat line and implying confidence it doesn't have. */
  is_fitted: boolean;
}

export interface Anomaly {
  date: string;
  category: string;
  amount: string;
  expected: string;
  z_score: number;
}

export interface ForecastResponse {
  overall: ForecastSeries;
  by_category: ForecastSeries[];
  anomalies: Anomaly[];
}

export interface CategorizationQuality {
  predictions: number;
  accepted: number;
  acceptance_rate: number;
  avg_confidence: number;
}

/** Frames pushed by the server over WS /ws/voice. */
export type WsMessage =
  | { type: "ready" }
  | { type: "partial"; transcript: string }
  | { type: "final"; result: VoiceResult }
  | { type: "error"; detail: string };
