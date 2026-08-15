import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge Tailwind classes with later ones winning.
 *
 * Plain string concatenation loses: `"p-2" + " p-4"` leaves both in the class
 * list and the winner depends on CSS source order, not call order. twMerge
 * resolves conflicts by Tailwind's own grouping rules.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Format a decimal string from the API for display. */
export function formatMoney(amount: string | number | null, currency = "USD"): string {
  if (amount === null) return "—";
  const value = typeof amount === "string" ? Number.parseFloat(amount) : amount;
  if (Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function formatMonth(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", {
    month: "short",
    year: "2-digit",
  });
}

/** Confidence -> presentation. Thresholds match the SQL `confidence_band`
 *  buckets so the web app and Power BI tell the same story. */
export function confidenceBand(confidence: number | null): {
  label: string;
  className: string;
} {
  if (confidence === null) {
    return { label: "manual", className: "bg-cream-200 text-ink-muted" };
  }
  if (confidence >= 0.8) {
    return { label: `${Math.round(confidence * 100)}%`, className: "bg-mint-100 text-forest-700" };
  }
  if (confidence >= 0.5) {
    return { label: `${Math.round(confidence * 100)}%`, className: "bg-amber-100 text-amber-800" };
  }
  return { label: `${Math.round(confidence * 100)}%`, className: "bg-rose-100 text-rose-700" };
}

/**
 * Stable colour per category, so a category keeps its colour across charts.
 *
 * Anchored on the brand greens and walked outward through teal, olive, and
 * clay rather than using a rainbow: a pie chart in ten unrelated hues fights
 * the rest of the page, and these all sit at a similar lightness so no one
 * slice jumps forward for a reason the data didn't earn.
 */
const CHART_COLORS = [
  "#03d47c", "#0b5132", "#4fb286", "#8de8bd", "#10693f",
  "#7fa88c", "#c9a227", "#c2703d", "#2f7d6b", "#a8bfa0",
];

export function categoryColor(category: string): string {
  let hash = 0;
  for (let i = 0; i < category.length; i++) {
    hash = (hash * 31 + category.charCodeAt(i)) | 0;
  }
  return CHART_COLORS[Math.abs(hash) % CHART_COLORS.length];
}
