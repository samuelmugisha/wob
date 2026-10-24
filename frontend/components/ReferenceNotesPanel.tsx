"use client";

import { useCallback, useEffect, useState } from "react";
import { api, formatDate, type Me, type ReferenceNote } from "@/lib/api";

const MAX_NOTES = 4;

type Draft = { referee_name: string; notes: string };

/** What the finalist's references said: up to four notes, each with the reference's name. */
export default function ReferenceNotesPanel({ categoryId, finalistId }: { categoryId: string; finalistId: string }) {
  const [notes, setNotes] = useState<ReferenceNote[] | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [drafts, setDrafts] = useState<Draft[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.listReferenceNotes(categoryId, finalistId).then(setNotes, (e: Error) => setError(e.message));
  }, [categoryId, finalistId]);
  useEffect(load, [load]);
  useEffect(() => {
    api.me().then(setMe, () => setMe(null));
  }, []);
  const canEdit = me?.permissions.manage_evidence ?? false;

  function edit() {
    const current = (notes ?? []).map((n) => ({ referee_name: n.referee_name, notes: n.notes }));
    setDrafts(current.length ? current : [{ referee_name: "", notes: "" }]);
    setError(null);
  }

  function update(i: number, patch: Partial<Draft>) {
    setDrafts((all) => all!.map((d, j) => (j === i ? { ...d, ...patch } : d)));
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    const filled = drafts!.filter((d) => d.referee_name.trim() || d.notes.trim());
    if (filled.some((d) => !d.referee_name.trim() || !d.notes.trim())) {
      setError("Give each reference both a name and notes, or remove it.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setNotes(await api.saveReferenceNotes(categoryId, finalistId, filled));
      setDrafts(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <div className="toolbar">
        <h2 style={{ margin: 0 }}>Reference notes</h2>
        {canEdit && !drafts && (
          <button className="secondary" onClick={edit}>
            {notes?.length ? "Edit notes" : "Add notes"}
          </button>
        )}
      </div>
      <p className="muted small" style={{ marginTop: 0 }}>
        What the finalist&apos;s references said, recorded by a coordinator: up to {MAX_NOTES} references.
      </p>
      {error && <div className="notice error">{error}</div>}

      {drafts ? (
        <form onSubmit={save} className="reference-form">
          {drafts.map((d, i) => (
            <fieldset key={i} className="criterion-row">
              <legend>Reference {i + 1}</legend>
              <div className="field">
                <label htmlFor={`ref-name-${i}`}>Name of reference</label>
                <input
                  id={`ref-name-${i}`}
                  value={d.referee_name}
                  maxLength={200}
                  onChange={(e) => update(i, { referee_name: e.target.value })}
                />
              </div>
              <div className="field">
                <label htmlFor={`ref-notes-${i}`}>Notes from the reference</label>
                <textarea
                  id={`ref-notes-${i}`}
                  rows={4}
                  value={d.notes}
                  maxLength={8000}
                  onChange={(e) => update(i, { notes: e.target.value })}
                />
              </div>
              <button
                type="button"
                className="link small"
                onClick={() => setDrafts((all) => all!.filter((_, j) => j !== i))}
              >
                Remove this reference
              </button>
            </fieldset>
          ))}
          <div className="inline-form">
            {drafts.length < MAX_NOTES && (
              <button
                type="button"
                className="secondary"
                onClick={() => setDrafts((all) => [...all!, { referee_name: "", notes: "" }])}
              >
                Add a reference ({drafts.length} of {MAX_NOTES})
              </button>
            )}
            <button type="submit" disabled={busy}>
              {busy ? "Saving…" : "Save notes"}
            </button>
            <button type="button" className="secondary" onClick={() => setDrafts(null)} disabled={busy}>
              Cancel
            </button>
          </div>
        </form>
      ) : notes === null ? (
        <p className="muted">Loading…</p>
      ) : notes.length === 0 ? (
        <div className="empty small">No reference notes yet.</div>
      ) : (
        <div className="reference-notes">
          {notes.map((n) => (
            <article key={n.position} className="claim">
              <strong>{n.referee_name}</strong>
              <p className="reference-text">{n.notes}</p>
              <div className="muted small">
                Recorded {formatDate(n.updated_at)}
                {n.updated_by && ` by ${n.updated_by}`}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
