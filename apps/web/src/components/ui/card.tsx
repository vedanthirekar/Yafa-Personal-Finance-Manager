import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Cards are large-radius, flat, and separated by a hairline rather than a
 * shadow. On a cream page a drop shadow reads as grey haze; a 1px border in
 * the next cream step up reads as a clean edge.
 */
export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("rounded-card border border-cream-300 bg-cream-50", className)}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col space-y-1.5 p-6", className)} {...props} />;
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3 className={cn("font-display text-lg font-semibold text-ink", className)} {...props} />
  );
}

export function CardDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm text-ink-muted", className)} {...props} />;
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-6 pt-0", className)} {...props} />;
}

export function CardFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex items-center p-6 pt-0", className)} {...props} />;
}

/**
 * A single headline number. Used across the overview and insights pages.
 *
 * `tone="dark"` flips it to the deep-green treatment. Exactly one card per row
 * should use it -- it is how the eye is told which number is the headline,
 * and if every card is dark none of them is.
 */
export function StatCard({
  label,
  value,
  hint,
  tone = "light",
  className,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: "light" | "dark";
  className?: string;
}) {
  const dark = tone === "dark";
  return (
    <div
      className={cn(
        "rounded-card border p-6",
        dark
          ? "border-forest-900 bg-forest-900 text-cream-50"
          : "border-cream-300 bg-cream-50 text-ink",
        className,
      )}
    >
      <p
        className={cn(
          "text-xs font-medium uppercase tracking-wider",
          dark ? "text-mint-300" : "text-ink-subtle",
        )}
      >
        {label}
      </p>
      <div className="mt-3 font-display text-3xl font-semibold tabular-nums">{value}</div>
      {hint ? (
        <p className={cn("mt-2 text-xs", dark ? "text-mint-300/80" : "text-ink-subtle")}>
          {hint}
        </p>
      ) : null}
    </div>
  );
}
