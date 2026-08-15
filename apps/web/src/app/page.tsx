import { ArrowRight, BarChart3, Check, Mic, Sparkles } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";

/**
 * Marketing landing page.
 *
 * A plain server component -- no hooks, no `"use client"`, no data fetching.
 * Everything here is static markup, so Next renders it once at build time and
 * ships zero JavaScript for it. That is worth protecting: if you ever need
 * state on this page, put it in a small client component and import it, rather
 * than marking the whole page client.
 *
 * The app itself lives behind /login; this page's only job is to explain what
 * YAFA does and send you there.
 */

const BULLETS = [
  {
    lead: "Speak, don't type.",
    rest: "Say “twelve fifty at Starbucks” and the amount, merchant, and date come out the other side.",
  },
  {
    lead: "It learns your categories.",
    rest: "Sentence embeddings match each description against what you've spent on before — correct it once and it remembers.",
  },
  {
    lead: "Nothing saves itself.",
    rest: "Every transaction is a proposal until you approve it. Speech recognition mishears; you get the last word.",
  },
];

const FEATURES = [
  {
    icon: Mic,
    title: "Voice capture",
    body: "Audio streams to a local Whisper model over a WebSocket and comes back as partial transcripts while you're still talking. No audio leaves the machine.",
  },
  {
    icon: Sparkles,
    title: "Semantic categorization",
    body: "A distilled BERT encoder embeds the description and the nearest labelled neighbours vote on the category. Below a similarity threshold it says it doesn't know, rather than guessing.",
  },
  {
    icon: BarChart3,
    title: "Spend forecasting",
    body: "Monthly totals are projected forward with prediction intervals, and per-category z-scores flag the months that broke pattern.",
  },
];

const STACK = ["FastAPI", "Whisper", "BERT", "Qdrant", "PostgreSQL", "Next.js", "Power BI"];

export default function Home() {
  return (
    <div className="bg-forest-950">
      {/* Announcement strip. Mirrors the reference's top bar. */}
      <div className="flex items-center justify-center gap-2.5 bg-forest-900 px-4 py-2.5 text-center text-sm text-cream-100">
        <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-mint-500">
          <Sparkles className="h-3 w-3 text-forest-950" />
        </span>
        <span className="text-cream-300">
          Say what you spent. It transcribes, categorizes, and files it.
        </span>
      </div>

      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-7">
        <span className="font-display text-2xl font-semibold text-cream-50">YAFA</span>
        <Button asChild size="sm" className="h-10 px-6 text-sm">
          <Link href="/login">Sign in</Link>
        </Button>
      </header>

      {/* ---------------------------------------------------------------- Hero */}
      <section className="mx-auto grid max-w-6xl gap-14 px-6 pb-24 pt-8 lg:grid-cols-[1.05fr_1fr] lg:items-center lg:gap-10">
        <div>
          <h1 className="font-display text-5xl leading-[1.05] text-cream-50 sm:text-6xl">
            The <em className="italic text-mint-500">easiest</em> way
            <br />
            to log an expense
          </h1>

          <ul className="mt-9 space-y-4">
            {BULLETS.map((b) => (
              <li key={b.lead} className="flex gap-3.5">
                <Check className="mt-0.5 h-5 w-5 shrink-0 text-mint-500" strokeWidth={3} />
                <p className="text-[15px] leading-relaxed text-cream-300">
                  <strong className="font-semibold text-cream-50">{b.lead}</strong> {b.rest}
                </p>
              </li>
            ))}
          </ul>

          <div className="mt-10 flex flex-wrap items-center gap-4">
            <Button asChild size="lg">
              <Link href="/login">
                Try the demo
                <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
            <p className="text-sm text-cream-300/70">18 months of sample data. No signup.</p>
          </div>
        </div>

        {/* Static product mock. Not a screenshot -- real markup, so it stays
            sharp at any zoom and never goes stale against the real UI. */}
        <div className="rounded-card border border-forest-800 bg-cream-50 p-1.5 shadow-2xl shadow-black/40">
          <div className="rounded-[1rem] bg-white p-5">
            <div className="flex items-center justify-between">
              <p className="font-display text-lg font-semibold">Today</p>
              <span className="rounded-full bg-mint-100 px-2.5 py-0.5 text-xs font-medium text-forest-700">
                3 to review
              </span>
            </div>

            <div className="mt-4 space-y-2.5">
              {[
                { desc: "Starbucks", cat: "Food", amt: "$12.50", conf: "94%" },
                { desc: "Uber to airport", cat: "Transportation", amt: "$38.20", conf: "88%" },
                { desc: "Spotify", cat: "Subscription", amt: "$10.99", conf: "71%" },
              ].map((row) => (
                <div
                  key={row.desc}
                  className="flex items-center gap-3 rounded-xl border border-cream-200 bg-cream-50 px-3.5 py-3"
                >
                  <span className="h-8 w-1.5 shrink-0 rounded-full bg-mint-500" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{row.desc}</p>
                    <p className="text-xs text-ink-subtle">{row.cat}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-semibold tabular-nums">{row.amt}</p>
                    <p className="text-xs text-ink-subtle">{row.conf} sure</p>
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-4 flex items-center gap-2.5 rounded-xl bg-forest-950 px-4 py-3">
              <Mic className="h-4 w-4 shrink-0 text-mint-500" />
              <p className="text-sm text-cream-300">
                &ldquo;twelve fifty at Starbucks&rdquo;
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* --------------------------------------------------------------- Stack */}
      <section className="bg-forest-700 px-6 py-14">
        <p className="text-center font-display text-2xl text-cream-50">
          Built on the boring, reliable parts
        </p>
        <div className="mx-auto mt-8 flex max-w-4xl flex-wrap items-center justify-center gap-x-10 gap-y-4">
          {STACK.map((name) => (
            <span key={name} className="text-lg font-medium text-cream-100/70">
              {name}
            </span>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------------ Features */}
      <section className="px-6 py-24">
        <h2 className="text-center font-display text-4xl text-cream-50">Features</h2>

        <div className="mx-auto mt-14 grid max-w-6xl gap-6 md:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, body }) => (
            <div
              key={title}
              className="rounded-card border border-forest-800 bg-forest-900 p-7"
            >
              <span className="grid h-11 w-11 place-items-center rounded-xl bg-mint-500">
                <Icon className="h-5 w-5 text-forest-950" />
              </span>
              <h3 className="mt-5 font-display text-xl font-semibold text-cream-50">
                {title}
              </h3>
              <p className="mt-3 text-sm leading-relaxed text-cream-300/80">{body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------------- Closing */}
      <section className="bg-cream-100 px-6 py-24">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="font-display text-4xl text-ink">
            Stop typing your receipts in
          </h2>
          <p className="mt-4 text-ink-muted">
            The demo seeds a full account and drops you straight into it. Nothing to
            install, nothing to sign up for.
          </p>
          <Button asChild size="lg" className="mt-8">
            <Link href="/login">
              Try the demo
              <ArrowRight className="h-4 w-4" />
            </Link>
          </Button>
        </div>
      </section>

      <footer className="border-t border-forest-800 px-6 py-8">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 text-sm text-cream-300/50 sm:flex-row">
          <span className="font-display text-lg text-cream-50">YAFA</span>
          <span>Yet Another Finance App</span>
        </div>
      </footer>
    </div>
  );
}
