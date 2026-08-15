"use client";

import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, Check, Loader2, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/utils";

type Mode = "login" | "register";

const PITCH = [
  "Just say it and we handle the rest"
];

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = React.useState<Mode>("login");
  const [form, setForm] = React.useState({
    username: "",
    password: "",
    email: "",
    name: "",
  });

  const onSuccess = () => router.push("/record");

  const login = useMutation({
    mutationFn: () => api.login(form.username, form.password),
    onSuccess,
  });
  const register = useMutation({
    mutationFn: () => api.register(form),
    onSuccess,
  });
  const demo = useMutation({ mutationFn: () => api.demoLogin(), onSuccess });

  const active = mode === "login" ? login : register;
  const error = active.error ?? demo.error;
  const busy = login.isPending || register.isPending || demo.isPending;

  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      {/* Left: the pitch, on the dark surface. Hidden below `lg` -- on a phone
          it would push the actual form below the fold, which is the one thing
          a sign-in page must never do. */}
      <div className="hidden flex-col justify-between bg-forest-950 p-12 lg:flex">
        <Link
          href="/"
          className="flex w-fit items-center gap-2 text-sm text-cream-300/70 transition-colors hover:text-cream-50"
        >
          <ArrowLeft className="h-4 w-4" />
          Back
        </Link>

        <div>
          <span className="font-display text-3xl font-semibold text-cream-50">YAFA</span>
          <h1 className="mt-6 max-w-md font-display text-4xl leading-tight text-cream-50">
            The <em className="italic text-mint-500">easiest</em> way to log your expenses
          </h1>

          <ul className="mt-8 space-y-3">
            {PITCH.map((line) => (
              <li key={line} className="flex items-start gap-3 text-[15px] text-cream-300">
                <Check className="mt-0.5 h-4 w-4 shrink-0 text-mint-500" strokeWidth={3} />
                {line}
              </li>
            ))}
          </ul>
        </div>

        <p className="text-sm text-cream-300/40">Yet Another Finance App</p>
      </div>

      {/* Right: the form. */}
      <div className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="lg:hidden">
            <span className="font-display text-3xl font-semibold">YAFA</span>
            <p className="mt-1 text-sm text-ink-muted">Just say it and we handle the rest</p>
          </div>

          {/* Demo first: the fastest path to seeing the app do something. */}
          <Button
            onClick={() => demo.mutate()}
            disabled={busy}
            className="mt-8 w-full lg:mt-0"
            size="lg"
          >
            {demo.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="h-4 w-4" />
            )}
            Try the demo
          </Button>
          <p className="mt-2.5 text-center text-xs text-ink-subtle">
            Demo acount with some sample data. 
          </p>

          <div className="my-7 flex items-center gap-3">
            <div className="h-px flex-1 bg-cream-300" />
            <span className="text-xs uppercase tracking-wider text-ink-subtle">or</span>
            <div className="h-px flex-1 bg-cream-300" />
          </div>

          <div className="mb-5 flex gap-1 rounded-full bg-cream-200 p-1">
            {(["login", "register"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={cn(
                  "flex-1 rounded-full px-3 py-2 text-sm font-medium transition-colors",
                  mode === m ? "bg-cream-50 text-ink shadow-sm" : "text-ink-subtle",
                )}
              >
                {m === "login" ? "Sign in" : "Create account"}
              </button>
            ))}
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              active.mutate();
            }}
            className="space-y-4"
          >
            {mode === "register" && (
              <>
                <div className="space-y-1.5">
                  <Label htmlFor="name">Name</Label>
                  <Input id="name" value={form.name} onChange={set("name")} required />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    value={form.email}
                    onChange={set("email")}
                    required
                  />
                </div>
              </>
            )}

            <div className="space-y-1.5">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                value={form.username}
                onChange={set("username")}
                autoComplete="username"
                required
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                value={form.password}
                onChange={set("password")}
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                minLength={mode === "register" ? 8 : undefined}
                required
              />
            </div>

            {error ? (
              <p className="text-sm text-rose-700">
                {error instanceof ApiError ? error.message : "Something went wrong"}
              </p>
            ) : null}

            <Button type="submit" variant="ink" className="w-full" size="lg" disabled={busy}>
              {active.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {mode === "login" ? "Sign in" : "Create account"}
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
