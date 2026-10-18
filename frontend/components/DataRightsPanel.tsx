"use client";

import { useState } from "react";
import { api, type Me } from "@/lib/api";

/** Access-request export and permanent erasure for one nomination (Act s.16, s.24). */
export default function DataRightsPanel({
  categoryId,
  finalistId,
  name,
  me,
}: {
  categoryId: string;
  finalistId: string;
  name: string;
  me: Me | null;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const canExport = me ? ["admin", "secretariat"].includes(me.role) : false;
  const canPurge = me?.role === "admin";
  if (!canExport && !canPurge) return null;

  async function purge(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api.purgeFinalist(categoryId, finalistId, reason.trim(), confirm);
      window.location.assign(`/categories/${categoryId}`);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section className="card">
      <h2>Data protection</h2>
      <div className="inline-form">
        {canExport && (
          <a className="button-link" href={api.exportUrl(categoryId, finalistId)}>
            Export all data (access request)
          </a>
        )}
        {canPurge && !open && (
          <button className="danger" onClick={() => setOpen(true)}>
            Erase all data…
          </button>
        )}
      </div>
      <p className="muted small">
        The export is a ZIP of everything held about this nomination, with other people identified by role
        only. Erasure permanently deletes it all, including files, ratings, ranking entries and reports.
      </p>
      {open && (
        <form onSubmit={purge} className="notice error purge-form">
          <strong>This cannot be undone.</strong> Category reports naming {name} are deleted too and can be
          regenerated. The audit log keeps a de-identified record that an erasure happened.
          <div className="field">
            <label htmlFor="purge-reason">Reason, without personal details</label>
            <input id="purge-reason" value={reason} onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. erasure request 2026-07" minLength={5} required />
          </div>
          <div className="field">
            <label htmlFor="purge-confirm">Type “{name}” to confirm</label>
            <input id="purge-confirm" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
          </div>
          <div className="inline-form">
            <button type="submit" className="danger" disabled={confirm.trim().toLowerCase() !== name.trim().toLowerCase()}>
              Erase permanently
            </button>
            <button type="button" className="secondary" onClick={() => setOpen(false)}>
              Cancel
            </button>
          </div>
          {error && <div>{error}</div>}
        </form>
      )}
    </section>
  );
}
