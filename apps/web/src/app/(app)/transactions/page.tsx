"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Search, Trash2 } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge, Input, Select } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { Transaction } from "@/lib/types";
import {
  CATEGORIES,
  categoryColor,
  confidenceBand,
  formatDate,
  formatMoney,
} from "@/lib/utils";

const PAGE_SIZE = 25;

export default function TransactionsPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = React.useState("");
  const [category, setCategory] = React.useState("");
  const [page, setPage] = React.useState(0);

  // Debounced so typing doesn't fire a request per keystroke.
  const [debouncedSearch, setDebouncedSearch] = React.useState("");
  React.useEffect(() => {
    const id = setTimeout(() => {
      setDebouncedSearch(search);
      setPage(0);
    }, 300);
    return () => clearTimeout(id);
  }, [search]);

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ["transactions", { search: debouncedSearch, category, page }],
    queryFn: () =>
      api.transactions({
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
        search: debouncedSearch || undefined,
        category: category || undefined,
      }),
    // Keeps the previous page visible while the next one loads, instead of
    // flashing an empty table on every page change.
    placeholderData: keepPreviousData,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["transactions"] });

  const correct = useMutation({
    mutationFn: ({ id, category }: { id: number; category: string }) =>
      api.correctCategory(id, category),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.deleteTransaction(id),
    onSuccess: invalidate,
  });

  const total = data?.total ?? 0;
  const pageCount = Math.ceil(total / PAGE_SIZE);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-3xl font-semibold">Transactions</h1>
        <p className="mt-2 text-sm text-ink-muted">
          {total.toLocaleString()} total
          {isFetching && !isLoading ? " · updating…" : ""}
        </p>
      </div>

      <div className="flex flex-wrap gap-3">
        <div className="relative min-w-64 flex-1">
          <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-subtle" />
          <Input
            placeholder="Search descriptions…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-10"
          />
        </div>
        <Select
          value={category}
          onChange={(e) => {
            setCategory(e.target.value);
            setPage(0);
          }}
          className="w-48"
        >
          <option value="">All categories</option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </Select>
      </div>

      <Card className="overflow-hidden">
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="h-6 w-6 animate-spin text-ink-subtle" />
            </div>
          ) : !data?.items.length ? (
            <p className="py-16 text-center text-sm text-ink-muted">
              Nothing here yet. Record one on the Record tab.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-cream-300 bg-cream-100 text-left text-xs uppercase tracking-wider text-ink-subtle">
                  <tr>
                    <th className="px-5 py-3 font-medium">Date</th>
                    <th className="px-5 py-3 font-medium">Description</th>
                    <th className="px-5 py-3 font-medium">Category</th>
                    <th className="px-5 py-3 text-right font-medium">Amount</th>
                    <th className="w-10 px-5 py-3" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-cream-200">
                  {data.items.map((t: Transaction) => {
                    const band = confidenceBand(t.confidence);
                    return (
                      <tr key={t.id} className="transition-colors hover:bg-cream-100">
                        <td className="whitespace-nowrap px-5 py-3.5 text-ink-subtle">
                          {formatDate(t.date)}
                        </td>
                        <td className="px-5 py-3.5">
                          <div className="flex items-center gap-3">
                            {/* Colour chip keyed to the category, matching the
                                pie chart on Insights so the same category is
                                the same colour everywhere in the app. */}
                            <span
                              className="h-8 w-1.5 shrink-0 rounded-full"
                              style={{ backgroundColor: categoryColor(t.category) }}
                            />
                            <div className="min-w-0">
                              <div className="font-medium">{t.description}</div>
                              {t.merchant && (
                                <div className="text-xs text-ink-subtle">{t.merchant}</div>
                              )}
                            </div>
                          </div>
                        </td>
                        <td className="px-5 py-3.5">
                          <div className="flex items-center gap-2">
                            {/* Changing this posts a correction, not a plain
                                edit -- it also feeds Qdrant as training data. */}
                            <Select
                              value={t.category}
                              onChange={(e) =>
                                correct.mutate({ id: t.id, category: e.target.value })
                              }
                              className="h-9 w-36 text-xs"
                            >
                              {CATEGORIES.map((c) => (
                                <option key={c} value={c}>
                                  {c}
                                </option>
                              ))}
                              {!CATEGORIES.includes(t.category) && (
                                <option value={t.category}>{t.category}</option>
                              )}
                            </Select>
                            <Badge className={band.className} title="Model confidence">
                              {band.label}
                            </Badge>
                          </div>
                        </td>
                        <td className="whitespace-nowrap px-5 py-3.5 text-right font-semibold tabular-nums">
                          {formatMoney(t.amount, t.currency)}
                        </td>
                        <td className="px-5 py-3.5">
                          <Button
                            size="icon"
                            variant="ghost"
                            className="h-8 w-8 text-ink-subtle hover:bg-rose-50 hover:text-rose-700"
                            onClick={() => remove.mutate(t.id)}
                            title="Delete"
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {pageCount > 1 && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-ink-subtle">
            Page {page + 1} of {pageCount}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => p + 1)}
              disabled={page + 1 >= pageCount}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
