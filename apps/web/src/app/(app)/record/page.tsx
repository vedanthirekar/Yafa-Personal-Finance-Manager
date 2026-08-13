"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, Mic, Square, X } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge, Input, Label, Select } from "@/components/ui/input";
import { useVoiceRecorder } from "@/hooks/use-voice-recorder";
import { api } from "@/lib/api";
import type { VoiceResult } from "@/lib/types";
import { cn, confidenceBand, formatMoney } from "@/lib/utils";

const CATEGORIES = [
  "Food", "Transportation", "Apparel", "Household", "Health",
  "Education", "Entertainment", "Social Life", "Tourism", "Subscription",
];

/** Bars are driven by the live RMS level, with a fixed per-bar offset so the
 *  shape looks like a waveform rather than every bar moving in lockstep. */
function Waveform({ level, active }: { level: number; active: boolean }) {
  const bars = 40;
  return (
    <div className="flex h-16 items-center justify-center gap-1">
      {Array.from({ length: bars }, (_, i) => {
        const offset = Math.sin((i / bars) * Math.PI * 3) * 0.35 + 0.65;
        const height = active ? Math.max(4, level * offset * 64) : 4;
        return (
          <div
            key={i}
            className={cn(
              "w-1 rounded-full transition-all duration-75",
              active ? "bg-indigo-500" : "bg-slate-200 dark:bg-slate-700",
            )}
            style={{ height: `${height}px` }}
          />
        );
      })}
    </div>
  );
}

export default function RecordPage() {
  const queryClient = useQueryClient();
  const recorder = useVoiceRecorder();
  const [draft, setDraft] = React.useState<VoiceResult | null>(null);
  const [saved, setSaved] = React.useState(false);

  // The WebSocket persists the transaction on finalize, so the draft here is
  // for reviewing and correcting what was heard.
  React.useEffect(() => {
    if (recorder.result) {
      setDraft(recorder.result);
      setSaved(false);
      void queryClient.invalidateQueries({ queryKey: ["transactions"] });
    }
  }, [recorder.result, queryClient]);

  const save = useMutation({
    mutationFn: (result: VoiceResult) => api.confirmVoice(result),
    onSuccess: () => {
      setSaved(true);
      void queryClient.invalidateQueries({ queryKey: ["transactions"] });
      void queryClient.invalidateQueries({ queryKey: ["breakdown"] });
    },
  });

  const recording = recorder.state === "recording";
  const busy = recorder.state === "connecting" || recorder.state === "processing";

  const patch = (changes: Partial<VoiceResult>) =>
    setDraft((d) => (d ? { ...d, ...changes } : d));

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Record an expense</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Just say it — &ldquo;twelve fifty at Starbucks&rdquo;. Amount, merchant, and
          category are worked out for you.
        </p>
      </div>

      <Card>
        <CardContent className="space-y-4 p-8 pt-8">
          <Waveform level={recorder.level} active={recording} />

          <div className="flex items-center justify-center gap-3">
            {!recording ? (
              <Button
                size="lg"
                onClick={() => void recorder.start()}
                disabled={busy}
                className="gap-2 rounded-full px-8"
              >
                {busy ? (
                  <Loader2 className="h-5 w-5 animate-spin" />
                ) : (
                  <Mic className="h-5 w-5" />
                )}
                {recorder.state === "processing" ? "Transcribing…" : "Start recording"}
              </Button>
            ) : (
              <>
                <Button
                  size="lg"
                  variant="destructive"
                  onClick={recorder.stop}
                  className="gap-2 rounded-full px-8"
                >
                  <Square className="h-4 w-4 fill-current" />
                  Stop · {String(Math.floor(recorder.seconds / 60)).padStart(2, "0")}:
                  {String(recorder.seconds % 60).padStart(2, "0")}
                </Button>
                <Button size="icon" variant="ghost" onClick={recorder.cancel} title="Cancel">
                  <X className="h-5 w-5" />
                </Button>
              </>
            )}
          </div>

          {/* Interim transcript. Explicitly marked as provisional, because it
              will be replaced by the final pass. */}
          {recording && (
            <p className="min-h-6 text-center text-sm italic text-slate-500 dark:text-slate-400">
              {recorder.partial || "Listening…"}
            </p>
          )}

          {recorder.error && (
            <p className="text-center text-sm text-rose-600 dark:text-rose-400">
              {recorder.error}
            </p>
          )}
        </CardContent>
      </Card>

      {draft && (
        <Card>
          <CardContent className="space-y-4 p-6 pt-6">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="text-xs uppercase tracking-wide text-slate-400">Heard</p>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                  &ldquo;{draft.transcript}&rdquo;
                </p>
              </div>
              <Badge className="shrink-0 bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                via {draft.extraction_method}
              </Badge>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label htmlFor="amount">Amount</Label>
                <Input
                  id="amount"
                  inputMode="decimal"
                  value={draft.amount ?? ""}
                  placeholder="0.00"
                  onChange={(e) => patch({ amount: e.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="date">Date</Label>
                <Input
                  id="date"
                  type="date"
                  value={draft.date}
                  onChange={(e) => patch({ date: e.target.value })}
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="description">Description</Label>
              <Input
                id="description"
                value={draft.description}
                onChange={(e) => patch({ description: e.target.value })}
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label htmlFor="merchant">Merchant</Label>
                <Input
                  id="merchant"
                  value={draft.merchant ?? ""}
                  placeholder="—"
                  onChange={(e) => patch({ merchant: e.target.value || null })}
                />
              </div>
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <Label htmlFor="category">Category</Label>
                  <Badge className={confidenceBand(draft.category ? draft.confidence : null).className}>
                    {draft.category
                      ? confidenceBand(draft.confidence).label
                      : "unsure"}
                  </Badge>
                </div>
                <Select
                  id="category"
                  value={draft.category ?? ""}
                  onChange={(e) => patch({ category: e.target.value || null })}
                >
                  <option value="">Pick a category…</option>
                  {CATEGORIES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </Select>
              </div>
            </div>

            {!draft.amount && (
              <p className="text-sm text-amber-600 dark:text-amber-400">
                No amount was picked up — add one before saving.
              </p>
            )}

            <div className="flex items-center gap-3 pt-2">
              <Button
                onClick={() => save.mutate(draft)}
                disabled={!draft.amount || !draft.category || save.isPending || saved}
                className="gap-2"
              >
                {save.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Check className="h-4 w-4" />
                )}
                {saved ? "Saved" : `Save ${formatMoney(draft.amount, draft.currency)}`}
              </Button>
              <Button
                variant="ghost"
                onClick={() => {
                  setDraft(null);
                  recorder.reset();
                }}
              >
                Discard
              </Button>
            </div>

            {save.error && (
              <p className="text-sm text-rose-600 dark:text-rose-400">
                {(save.error as Error).message}
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
