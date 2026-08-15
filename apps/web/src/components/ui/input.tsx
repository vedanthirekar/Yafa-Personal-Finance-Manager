import * as React from "react";

import { cn } from "@/lib/utils";

/** Shared between <input> and <select> so the two never drift apart visually. */
const fieldStyles =
  "flex h-11 w-full rounded-xl border border-cream-300 bg-white px-3.5 py-2 text-sm text-ink transition-colors placeholder:text-ink-subtle focus-visible:border-mint-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-500/30 disabled:cursor-not-allowed disabled:opacity-50";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type, ...props }, ref) => (
    <input type={type} ref={ref} className={cn(fieldStyles, className)} {...props} />
  ),
);
Input.displayName = "Input";

export const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(({ className, ...props }, ref) => (
  // A native <select> rather than a Radix listbox: it is keyboard- and
  // screen-reader-correct for free, and renders as the platform picker on
  // mobile. The custom version would be more code for less accessibility.
  <select ref={ref} className={cn(fieldStyles, "pr-8", className)} {...props} />
));
Select.displayName = "Select";

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn(
        "text-xs font-medium uppercase tracking-wider text-ink-subtle",
        className,
      )}
      {...props}
    />
  );
}

export function Badge({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
        className,
      )}
      {...props}
    />
  );
}
