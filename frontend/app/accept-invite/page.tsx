"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api } from "@/lib/api";

function AcceptForm() {
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (password !== confirm) return setError("The two passwords don't match.");
    setBusy(true);
    setError(null);
    try {
      const { user } = await api.acceptInvite(token, password);
      window.location.assign(user.mfa_setup_required ? "/account?setup=mfa" : "/");
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  if (!token) {
    return <div className="card auth-card notice error">This link is incomplete. Ask an administrator for a new one.</div>;
  }
  return (
    <form className="card auth-card" onSubmit={submit}>
      <h1>Set your password</h1>
      <p className="muted small">
        At least 12 characters. A few unrelated words make a strong, memorable password.
      </p>
      <div className="field">
        <label htmlFor="pw">New password</label>
        <input id="pw" type="password" autoComplete="new-password" minLength={12} value={password}
          onChange={(e) => setPassword(e.target.value)} required autoFocus />
      </div>
      <div className="field">
        <label htmlFor="pw2">Repeat it</label>
        <input id="pw2" type="password" autoComplete="new-password" value={confirm}
          onChange={(e) => setConfirm(e.target.value)} required />
      </div>
      {error && <div className="notice error">{error}</div>}
      <button type="submit" disabled={busy}>{busy ? "Saving…" : "Set password and sign in"}</button>
    </form>
  );
}

export default function AcceptInvitePage() {
  return (
    <Suspense>
      <AcceptForm />
    </Suspense>
  );
}
