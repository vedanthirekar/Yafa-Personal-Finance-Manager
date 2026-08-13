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
    return { label: "manual", className: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300" };
  }
  if (confidence >= 0.8) {
    return { label: `${Math.round(confidence * 100)}%`, className: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300" };
  }
  if (confidence >= 0.5) {
    return { label: `${Math.round(confidence * 100)}%`, className: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300" };
  }
  return { label: `${Math.round(confidence * 100)}%`, className: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300" };
}

/** Stable colour per category, so a category keeps its colour across charts. */
const CHART_COLORS = [
  "#6366f1", "#14b8a6", "#f59e0b", "#ec4899", "#8b5cf6",
  "#06b6d4", "#84cc16", "#f97316", "#3b82f6", "#ef4444",
];

export function categoryColor(category: string): string {
  let hash = 0;
  for (let i = 0; i < category.length; i++) {
    hash = (hash * 31 + category.charCodeAt(i)) | 0;
  }
  return CHART_COLORS[Math.abs(hash) % CHART_COLORS.length];
}
