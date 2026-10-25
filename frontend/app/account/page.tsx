"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api, type Me, ROLE_LABELS } from "@/lib/api";

function TwoFactor({ me, onEnabled }: { me: Me; onEnabled: () => void }) {
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (me.mfa_enabled) {
    return <p className="small">✓ Two-factor authentication is on. Ask an administrator to reset it if you lose your device.</p>;
  }

  async function start() {
    setError(null);
    try {
      setSetup(await api.mfaSetup());
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function confirm(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api.mfaEnable(code.trim());
      onEnabled();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <>
      <p className="small">
        Protects your account with a code from an authenticator app (Microsoft Authenticator, Google
        Authenticator, 1Password and similar) in addition to your password.
      </p>
      {!setup ? (
        <button onClick={start}>Set up two-factor authentication</button>
      ) : (
        <form onSubmit={confirm} className="mfa-setup">
          <ol className="small">
            <li>
              In your authenticator app, add an account and enter this key:
              <div className="secret">{setup.secret.match(/.{1,4}/g)?.join(" ")}</div>
              On a phone you can instead open <a href={setup.otpauth_uri}>this setup link</a>.
            </li>
            <li>Enter the 6-digit code the app shows:</li>
          </ol>
          <div className="inline-form">
            <input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,8}" value={code}
              onChange={(e) => setCode(e.target.value)} placeholder="123 456" required style={{ maxWidth: 160 }} />
            <button type="submit">Turn on</button>
          </div>
        </form>
      )}
      {error && <div className="notice error">{error}</div>}
    </>
  );
}

function PasswordChange() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    try {
      await api.changePassword(current, next);
      setCurrent("");
      setNext("");
      setMessage({ ok: true, text: "Password changed. Other devices have been signed out." });
    } catch (e) {
      setMessage({ ok: false, text: (e as Error).message });
    }
  }

  return (
    <form onSubmit={submit} className="form-row">
      <div className="field">
        <label htmlFor="cur">Current password</label>
        <input id="cur" type="password" autoComplete="current-password" value={current}
          onChange={(e) => setCurrent(e.target.value)} required />
      </div>
      <div className="field">
        <label htmlFor="new">New password (12+ characters)</label>
        <input id="new" type="password" autoComplete="new-password" minLength={8} value={next}
          onChange={(e) => setNext(e.target.value)} required />
      </div>
      <button type="submit">Change password</button>
      {message && <div className={`notice ${message.ok ? "success" : "error"}`} style={{ width: "100%" }}>{message.text}</div>}
    </form>
  );
}

function Account() {
  const setupRequested = useSearchParams().get("setup") === "mfa";
  const [me, setMe] = useState<Me | null>(null);
  const load = () => api.me().then(setMe, () => setMe(null));
  useEffect(() => {
    load();
  }, []);
  if (!me) return <p className="muted">Loading…</p>;

  return (
    <>
      <h1>Your account</h1>
      <p className="muted">
        {me.display_name} · {me.email} · {ROLE_LABELS[me.role as keyof typeof ROLE_LABELS] ?? me.role}
      </p>
      {(me.mfa_setup_required || setupRequested) && !me.mfa_enabled && (
        <div className="notice warning">
          {me.mfa_setup_required
            ? "Your role requires two-factor authentication. Set it up to continue."
            : "Set up two-factor authentication to protect your account."}
        </div>
      )}
      <section className="card">
        <h2>Two-factor authentication</h2>
        <TwoFactor me={me} onEnabled={() => (window.location.href = "/")} />
      </section>
      <section className="card">
        <h2>Password</h2>
        <PasswordChange />
      </section>
    </>
  );
}

export default function AccountPage() {
  return (
    <Suspense>
      <Account />
    </Suspense>
  );
}
