"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api, ApiError } from "@/lib/api";

function safeNext(next: string | null): string {
  // Only same-site paths, never "//host" or absolute URLs (open-redirect protection).
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

function LoginForm() {
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [needOtp, setNeedOtp] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { user } = await api.login(email.trim(), password, needOtp ? otp.trim() : undefined);
      window.location.assign(user.mfa_setup_required ? "/account?setup=mfa" : safeNext(params.get("next")));
    } catch (e) {
      if (e instanceof ApiError && e.code === "mfa_required") {
        setNeedOtp(true);
      } else {
        setError((e as Error).message);
        if (needOtp) setOtp("");
      }
      setBusy(false);
    }
  }

  return (
    <form className="card auth-card" onSubmit={submit}>
      <h1>Sign in</h1>
      <p className="muted small">For the awards secretariat, reviewers, judges and committee.</p>
      <div className="field">
        <label htmlFor="email">Email</label>
        <input id="email" type="email" autoComplete="username" value={email}
          onChange={(e) => setEmail(e.target.value)} required autoFocus disabled={needOtp} />
      </div>
      <div className="field">
        <label htmlFor="password">Password</label>
        <input id="password" type="password" autoComplete="current-password" value={password}
          onChange={(e) => setPassword(e.target.value)} required disabled={needOtp} />
      </div>
      {needOtp && (
        <div className="field">
          <label htmlFor="otp">Code from your authenticator app</label>
          <input id="otp" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,8}"
            value={otp} onChange={(e) => setOtp(e.target.value)} required autoFocus />
        </div>
      )}
      {error && <div className="notice error">{error}</div>}
      <button type="submit" disabled={busy}>{busy ? "Signing in…" : needOtp ? "Verify" : "Sign in"}</button>
      <p className="muted small">Forgotten your password? Ask an administrator for a new set-password link.</p>
    </form>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
