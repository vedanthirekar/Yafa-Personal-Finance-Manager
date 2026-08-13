"use client";

import { useMutation } from "@tanstack/react-query";
import { Loader2, Mic } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/utils";

type Mode = "login" | "register";

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
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-3xl font-semibold tracking-tight">YAFA</h1>
          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
            Say what you spent. It files itself.
          </p>
        </div>

        <Card>
          <CardContent className="p-6 pt-6">
            {/* Demo first: the fastest path to seeing the app do something. */}
            <Button
              onClick={() => demo.mutate()}
              disabled={busy}
              className="w-full"
              size="lg"
            >
              {demo.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Mic className="h-4 w-4" />
              )}
              Try the demo
            </Button>
            <p className="mt-2 text-center text-xs text-slate-500 dark:text-slate-400">
              18 months of sample data. No signup.
            </p>

            <div className="my-6 flex items-center gap-3">
              <div className="h-px flex-1 bg-slate-200 dark:bg-slate-800" />
              <span className="text-xs text-slate-400">or</span>
              <div className="h-px flex-1 bg-slate-200 dark:bg-slate-800" />
            </div>

            <div className="mb-4 flex gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-800">
              {(["login", "register"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  className={cn(
                    "flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                    mode === m
                      ? "bg-white text-slate-900 shadow-sm dark:bg-slate-950 dark:text-slate-100"
                      : "text-slate-500",
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
              className="space-y-3"
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
                <p className="text-sm text-rose-600 dark:text-rose-400">
                  {error instanceof ApiError ? error.message : "Something went wrong"}
                </p>
              ) : null}

              <Button type="submit" variant="secondary" className="w-full" disabled={busy}>
                {active.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                {mode === "login" ? "Sign in" : "Create account"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
