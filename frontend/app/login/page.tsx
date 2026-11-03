"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Button, ErrorNote, Field, Input } from "@/components/ui";
import { GlitchText } from "@/components/fx/GlitchText";
import { MatrixRain } from "@/components/fx/MatrixRain";
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
    <form onSubmit={submit} className="x-panel x-scanlines x-above-rain w-full max-w-sm space-y-4 p-6">
      <div className="mb-2 flex items-center gap-3">
        <XMark size={38} />
        <div>
          <GlitchText text="X" className="font-display text-xl font-semibold tracking-[0.4em] x-phosphor" />
          <div className="x-label">Operator authentication</div>
        </div>
      </div>
      <div className="border-y border-green/10 py-1.5 font-mono text-[10.5px] tracking-[0.14em] text-green/50">
        SECURE CHANNEL // AI · QUANTUM · INTELLECT
      </div>
      <Field label="Email">
        <Input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </Field>
      <Field label="Password">
        <Input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
      </Field>
      <ErrorNote error={error} />
      <Button type="submit" variant="primary" className="w-full" loading={busy}>Authenticate</Button>
      <p className="text-xs text-muted">Accounts are created by an administrator.</p>
    </form>
  );
}

export default function LoginPage() {
  return (
    <main id="main" className="x-grid x-vignette relative flex min-h-dvh items-center justify-center overflow-hidden px-4">
      <MatrixRain opacity={0.28} />
      <div aria-hidden className="pointer-events-none fixed inset-0 bg-[radial-gradient(ellipse_at_center,transparent_15%,#050708_80%)]" />
      <Suspense>
        <LoginForm />
      </Suspense>
    </main>
  );
}
