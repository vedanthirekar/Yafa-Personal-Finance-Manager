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
 * One colour per category rather than a hashed lookup into a shared pool,
 * because the category set is closed: every category owns a hue and no two
 * can collide. The hashed version put Education, Food, and Transportation on
 * the same green in a seven-slice pie.
 *
 * Still anchored on the brand green, but walked around the wheel rather than
 * held at one hue — a donut is read by comparing neighbouring wedges, and ten
 * tones of the same green can't be told apart no matter how tidy they look in
 * a swatch row. Every pair is at least ΔE2000 17 apart, and lightness varies
 * too (L* 30–75) so the wedges stay separable in greyscale.
 */
const CHART_COLORS: Record<string, string> = {
  Food: "#03d47c",           // brand spring green
  Transportation: "#4a83c4", // blue
  Apparel: "#6d3f8f",        // plum
  Household: "#137a8c",      // teal
  Health: "#b5485d",         // berry
  Education: "#0b5132",      // pine, the brand dark
  Entertainment: "#e0b13a",  // amber
  "Social Life": "#c2703d",  // clay
  Tourism: "#6b7a45",        // olive
  Subscription: "#6b4f3f",   // mocha
};

/**
 * The categories the classifier can emit. Charts, filters, and the record
 * form all read this one list, and it is derived from the colour map so a
 * category can't be added to the UI without also being given a colour.
 */
export const CATEGORIES = Object.keys(CHART_COLORS);

/** Fallback pool for categories outside the closed set — older rows, or a
 *  model revision that emits something new before the UI catches up. */
const FALLBACK_COLORS = ["#8a6d9e", "#3f6f5f", "#a8572f", "#5b6f8a"];

export function categoryColor(category: string): string {
  const known = CHART_COLORS[category];
  if (known) return known;

  let hash = 0;
  for (let i = 0; i < category.length; i++) {
    hash = (hash * 31 + category.charCodeAt(i)) | 0;
  }
  return FALLBACK_COLORS[Math.abs(hash) % FALLBACK_COLORS.length];
}
