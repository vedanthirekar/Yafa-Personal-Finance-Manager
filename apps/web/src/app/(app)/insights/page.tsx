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

export default function InsightsPage() {
  const forecast = useQuery({ queryKey: ["forecast"], queryFn: () => api.forecast(6) });
  const breakdown = useQuery({ queryKey: ["breakdown"], queryFn: () => api.categoryBreakdown() });
  const quality = useQuery({
    queryKey: ["quality"],
    queryFn: () => api.categorizationQuality(),
  });

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

  const loading = forecast.isLoading || breakdown.isLoading;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    );
  }

  const overall = forecast.data?.overall;
  const nextMonth = overall?.forecast[0];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Insights</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Spend history, projection, and how the categorizer is doing.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Total spend" value={formatMoney(totalSpend)} />
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
          label="Avg model confidence"
          value={quality.data ? quality.data.avg_confidence.toFixed(2) : "—"}
          hint={
            quality.data ? `${quality.data.predictions} predictions recorded` : undefined
          }
        />
        <StatCard
          label="Suggestions kept"
          value={
            quality.data ? `${Math.round(quality.data.acceptance_rate * 100)}%` : "—"
          }
          hint="How often you accepted the model's category"
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Monthly spend and forecast</CardTitle>
          {overall && (
            /* State the model and whether it actually fitted. A mean baseline
               drawn identically to a real ARIMA fit would imply confidence
               the projection doesn't have. */
            <p className="text-xs text-slate-400">
              {overall.is_fitted
                ? `${overall.model} · 80% prediction interval`
                : `${overall.model} · not enough history for a fitted model`}
            </p>
          )}
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={320}>
            <ComposedChart data={series} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-slate-200 dark:stroke-slate-800" />
              <XAxis
                dataKey="date"
                tickFormatter={formatMonth}
                tick={{ fontSize: 12 }}
                stroke="currentColor"
                className="text-slate-400"
              />
              <YAxis
                tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
                tick={{ fontSize: 12 }}
                stroke="currentColor"
                className="text-slate-400"
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
                contentStyle={{ borderRadius: 8, fontSize: 12 }}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Area
                dataKey="band"
                stroke="none"
                fill="#6366f1"
                fillOpacity={0.12}
                name="80% range"
                connectNulls
              />
              <Line
                dataKey="actual"
                stroke="#6366f1"
                strokeWidth={2}
                dot={false}
                name="Actual"
                connectNulls
              />
              <Line
                dataKey="forecast"
                stroke="#6366f1"
                strokeWidth={2}
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
                >
                  {(breakdown.data ?? []).map((row) => (
                    <Cell key={row.category} fill={categoryColor(row.category)} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(value) =>
                    typeof value === "number" ? formatMoney(value) : "—"
                  }
                  contentStyle={{ borderRadius: 8, fontSize: 12 }}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Unusual months</CardTitle>
            <p className="text-xs text-slate-400">
              Category spend more than 2σ above its own average
            </p>
          </CardHeader>
          <CardContent className="space-y-2">
            {!forecast.data?.anomalies.length ? (
              <p className="py-8 text-center text-sm text-slate-500">
                Nothing unusual found.
              </p>
            ) : (
              forecast.data.anomalies.slice(0, 6).map((a) => (
                <div
                  key={`${a.date}-${a.category}`}
                  className="flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 dark:border-amber-900 dark:bg-amber-950/40"
                >
                  <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium">{a.category}</div>
                    <div className="text-xs text-slate-500 dark:text-slate-400">
                      {formatMonth(a.date)} · usually {formatMoney(a.expected)}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm font-semibold tabular-nums">
                      {formatMoney(a.amount)}
                    </div>
                    <div className="text-xs text-slate-400">{a.z_score}σ</div>
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
