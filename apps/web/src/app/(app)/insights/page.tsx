"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Loader2 } from "lucide-react";
import * as React from "react";
import {
  Area,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent, CardHeader, CardTitle, StatCard } from "@/components/ui/card";
import { api } from "@/lib/api";
import { categoryColor, formatMonth, formatMoney } from "@/lib/utils";

/** Recharts tooltips are inline-styled, not class-styled, so the palette has
 *  to be repeated here as literals. Declared once and shared by both charts. */
const TOOLTIP_STYLE = {
  borderRadius: 12,
  border: "1px solid #e2dfd3",
  backgroundColor: "#fcfbf7",
  fontSize: 12,
  color: "#002e22",
} as const;

export default function InsightsPage() {
  const forecast = useQuery({ queryKey: ["forecast"], queryFn: () => api.forecast(6) });
  const breakdown = useQuery({ queryKey: ["breakdown"], queryFn: () => api.categoryBreakdown() });

  /**
   * Actuals and projection share one chart, so they must share one array.
   * Each row carries `actual` OR `forecast`, never both -- Recharts skips
   * nulls, which is what produces two connected-but-distinct lines rather
   * than one line that inexplicably drops to zero at the boundary.
   */
  const series = React.useMemo(() => {
    const overall = forecast.data?.overall;
    if (!overall) return [];

    const rows = overall.history.map((p) => ({
      date: p.date,
      actual: Number.parseFloat(p.amount),
      forecast: null as number | null,
      band: null as [number, number] | null,
    }));

    // Repeat the last actual as the forecast's first point so the two lines
    // visually join instead of leaving a gap at the seam.
    const last = rows.at(-1);
    if (last) last.forecast = last.actual;

    for (const p of overall.forecast) {
      rows.push({
        date: p.date,
        actual: null as unknown as number,
        forecast: Number.parseFloat(p.amount),
        band:
          p.lower && p.upper
            ? [Number.parseFloat(p.lower), Number.parseFloat(p.upper)]
            : null,
      });
    }
    return rows;
  }, [forecast.data]);

  const totalSpend = React.useMemo(
    () =>
      breakdown.data?.reduce((sum, r) => sum + Number.parseFloat(r.total_amount), 0) ?? 0,
    [breakdown.data],
  );

  /**
   * The last two monthly buckets, for the headline cards.
   *
   * They are reported separately rather than as a month-over-month percentage:
   * the newest bucket is the month you're currently in, so it's partial, and
   * dividing a half-finished month by a complete one always reads as a
   * dramatic drop in spending that hasn't happened.
   */
  const history = forecast.data?.overall.history ?? [];
  const thisMonth = history.at(-1);
  const lastMonth = history.at(-2);

  const biggestCategory = React.useMemo(
    () =>
      [...(breakdown.data ?? [])].sort(
        (a, b) => Number.parseFloat(b.total_amount) - Number.parseFloat(a.total_amount),
      )[0],
    [breakdown.data],
  );

  const loading = forecast.isLoading || breakdown.isLoading;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 className="h-6 w-6 animate-spin text-ink-subtle" />
      </div>
    );
  }

  const overall = forecast.data?.overall;
  const nextMonth = overall?.forecast[0];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-3xl font-semibold">Insights</h1>
        <p className="mt-2 text-sm text-ink-muted">
          Where your money went, and where it&rsquo;s heading.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* The only dark card on the page: the number you actually came for. */}
        <StatCard
          tone="dark"
          label="This month so far"
          value={thisMonth ? formatMoney(thisMonth.amount) : "—"}
          hint={thisMonth ? formatMonth(thisMonth.date) : undefined}
        />
        <StatCard
          label="Last month"
          value={lastMonth ? formatMoney(lastMonth.amount) : "—"}
          hint={lastMonth ? formatMonth(lastMonth.date) : undefined}
        />
        <StatCard
          label="Next month (projected)"
          value={nextMonth ? formatMoney(nextMonth.amount) : "—"}
          hint={
            nextMonth?.lower && nextMonth.upper
              ? `80% range ${formatMoney(nextMonth.lower)}–${formatMoney(nextMonth.upper)}`
              : undefined
          }
        />
        <StatCard
          label="Biggest category"
          value={biggestCategory ? biggestCategory.category : "—"}
          hint={
            biggestCategory
              ? `${formatMoney(biggestCategory.total_amount)} · ${Math.round(
                  biggestCategory.pct_of_total,
                )}% of ${formatMoney(totalSpend)}`
              : undefined
          }
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Monthly spend and forecast</CardTitle>
          {overall && (
            /* Say whether the dotted line is a real projection or a flat
               average standing in for thin history -- drawing both the same way
               would imply confidence the second one doesn't have. The model's
               name is left out on purpose: "ARIMA(5, 1, 0)" tells the reader
               nothing they can act on. */
            <p className="text-xs text-ink-subtle">
              {overall.is_fitted
                ? `Projected from ${overall.history.length} months of history · shaded band is the likely range`
                : "Too little history to project — showing your average instead"}
            </p>
          )}
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={320}>
            <ComposedChart data={series} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-cream-300" />
              <XAxis
                dataKey="date"
                tickFormatter={formatMonth}
                tick={{ fontSize: 12 }}
                stroke="currentColor"
                className="text-ink-subtle"
              />
              <YAxis
                tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
                tick={{ fontSize: 12 }}
                stroke="currentColor"
                className="text-ink-subtle"
              />
              {/* Recharts types the formatter value as a broad ValueType
                  (number | string | array), so narrow it here rather than
                  asserting a type the library doesn't guarantee. */}
              <Tooltip
                formatter={(value) =>
                  typeof value === "number" ? formatMoney(value) : "—"
                }
                labelFormatter={(label) =>
                  typeof label === "string" ? formatMonth(label) : ""
                }
                contentStyle={TOOLTIP_STYLE}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {/* Actual and forecast share one colour and differ only by dash.
                  Two hues would imply two quantities; this is one series, part
                  measured and part projected. */}
              <Area
                dataKey="band"
                stroke="none"
                fill="#03d47c"
                fillOpacity={0.18}
                name="80% range"
                connectNulls
              />
              <Line
                dataKey="actual"
                stroke="#0b5132"
                strokeWidth={2.5}
                dot={false}
                name="Actual"
                connectNulls
              />
              <Line
                dataKey="forecast"
                stroke="#0b5132"
                strokeWidth={2.5}
                strokeDasharray="5 5"
                dot={false}
                name="Forecast"
                connectNulls
              />
            </ComposedChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Where it goes</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie
                  data={breakdown.data ?? []}
                  dataKey={(d) => Number.parseFloat(d.total_amount)}
                  nameKey="category"
                  innerRadius={60}
                  outerRadius={110}
                  paddingAngle={2}
                  stroke="none"
                >
                  {(breakdown.data ?? []).map((row) => (
                    <Cell key={row.category} fill={categoryColor(row.category)} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(value) =>
                    typeof value === "number" ? formatMoney(value) : "—"
                  }
                  contentStyle={TOOLTIP_STYLE}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Unusual months</CardTitle>
            <p className="text-xs text-ink-subtle">
              Category spend more than 2σ above its own average
            </p>
          </CardHeader>
          <CardContent className="space-y-2">
            {!forecast.data?.anomalies.length ? (
              <p className="py-8 text-center text-sm text-ink-muted">
                Nothing unusual found.
              </p>
            ) : (
              forecast.data.anomalies.slice(0, 6).map((a) => (
                <div
                  key={`${a.date}-${a.category}`}
                  className="flex items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-2.5"
                >
                  <AlertTriangle className="h-4 w-4 shrink-0 text-amber-700" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium">{a.category}</div>
                    <div className="text-xs text-ink-subtle">
                      {formatMonth(a.date)} · usually {formatMoney(a.expected)}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm font-semibold tabular-nums">
                      {formatMoney(a.amount)}
                    </div>
                    <div className="text-xs text-ink-subtle">{a.z_score}σ</div>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
