"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Button, ErrorNote, Field, Input } from "@/components/ui";
import { XMark } from "@/components/XMark";
import { useAuth } from "@/lib/auth";

function LoginForm() {
  const { login } = useAuth();
  const router = useRouter();
  const next = useSearchParams().get("next") || "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      router.replace(next.startsWith("/") ? next : "/");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="x-panel w-full max-w-sm space-y-4 p-6">
      <div className="mb-2 flex items-center gap-3">
        <XMark size={34} />
        <div>
          <div className="font-display text-lg font-semibold tracking-[0.3em]">X</div>
          <div className="x-label">Computational intelligence</div>
        </div>
      </div>
      <Field label="Email">
        <Input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </Field>
      <Field label="Password">
        <Input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
      </Field>
      <ErrorNote error={error} />
      <Button type="submit" variant="primary" className="w-full" loading={busy}>Enter X</Button>
      <p className="text-xs text-muted">Accounts are created by an administrator.</p>
    </form>
  );
}

export default function LoginPage() {
  return (
    <main id="main" className="x-grid x-vignette flex min-h-dvh items-center justify-center px-4">
      <Suspense>
        <LoginForm />
      </Suspense>
    </main>
  );
}
