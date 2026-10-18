"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Consent, formatDate, type Me } from "@/lib/api";

const PARTS: { key: "assessment" | "ai_processing" | "web_research"; label: string; help: string }[] = [
  { key: "assessment", label: "A. Assessment", help: "Optional before uploading evidence; if withdrawn, uploads stop." },
  {
    key: "ai_processing",
    label: "B. AI-assisted assessment abroad",
    help: "Claims and AI ratings via Anthropic (USA). Without it, reviewers rate by hand.",
  },
  { key: "web_research", label: "C. Public-source checks", help: "Web research about their claims." },
];

/** The finalist's consent as recorded from the signed notice (Act s.7, s.19). */
export default function ConsentPanel({
  categoryId,
  finalistId,
  me,
  onChanged,
}: {
  categoryId: string;
  finalistId: string;
  me: Me | null;
  onChanged: () => void;
}) {
  const [data, setData] = useState<{ current: Consent | null; history: Consent[] } | null>(null);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    assessment: true,
    ai_processing: false,
    web_research: false,
    notice_version: "v1",
    method: "signed_form" as Consent["method"],
    reference: "",
  });
  const [showHistory, setShowHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canRecord = me?.permissions.manage_evidence ?? false;

  const load = useCallback(() => {
    api.getConsent(categoryId, finalistId).then(setData, (e: Error) => setError(e.message));
  }, [categoryId, finalistId]);
  useEffect(load, [load]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api.recordConsent(categoryId, finalistId, { ...form, reference: form.reference.trim() || null });
      setEditing(false);
      load();
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!data) return null;
  const current = data.current;

  return (
    <section className="card">
      <div className="toolbar">
        <h2 style={{ margin: 0 }}>Consent</h2>
        {canRecord && !editing && (
          <button
            className="secondary"
            onClick={() => {
              if (current) setForm({ ...current, reference: current.reference ?? "" });
              setEditing(true);
            }}
          >
            {current ? "Update consent" : "Record consent"}
          </button>
        )}
      </div>
      {!current && (
        <div className="notice warning">
          No consent recorded. Record the finalist&apos;s signed consent before adding their evidence.
        </div>
      )}
      {current && (
        <div className="consent-badges">
          {PARTS.map((p) => (
            <span key={p.key} className={`badge${current[p.key] ? " success" : " muted"}`}>
              {current[p.key] ? "✓" : "✗"} {p.label}
            </span>
          ))}
          <div className="muted small">
            Notice {current.notice_version} · {current.method.replace("_", " ")}
            {current.reference && ` · ${current.reference}`} · recorded {formatDate(current.recorded_at)}
            {current.recorded_by && ` by ${current.recorded_by}`}
            {data.history.length > 1 && (
              <>
                {" · "}
                <button className="link small" onClick={() => setShowHistory(!showHistory)}>
                  {showHistory ? "hide" : "show"} history ({data.history.length})
                </button>
              </>
            )}
          </div>
          {showHistory && (
            <ol className="small muted review-history">
              {data.history.map((h) => (
                <li key={h.recorded_at}>
                  {formatDate(h.recorded_at)}: A {h.assessment ? "yes" : "no"}, B {h.ai_processing ? "yes" : "no"}, C{" "}
                  {h.web_research ? "yes" : "no"} ({h.notice_version}, {h.method.replace("_", " ")})
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
      {editing && (
        <form onSubmit={save} className="consent-form">
          {PARTS.map((p) => (
            <label key={p.key} className="radio">
              <input
                type="checkbox"
                checked={form[p.key]}
                onChange={(e) => {
                  const next = { ...form, [p.key]: e.target.checked };
                  if (p.key === "assessment" && !e.target.checked) {
                    next.ai_processing = false;
                    next.web_research = false;
                  }
                  setForm(next);
                }}
                disabled={p.key !== "assessment" && !form.assessment}
              />
              <span>
                <strong>{p.label}</strong> <span className="muted small">{p.help}</span>
              </span>
            </label>
          ))}
          <div className="form-row">
            <div className="field" style={{ flexGrow: 0, flexBasis: 120 }}>
              <label htmlFor="notice">Notice version</label>
              <input id="notice" value={form.notice_version} onChange={(e) => setForm({ ...form, notice_version: e.target.value })} required />
            </div>
            <div className="field" style={{ flexGrow: 0, flexBasis: 160 }}>
              <label htmlFor="method">How given</label>
              <select id="method" value={form.method} onChange={(e) => setForm({ ...form, method: e.target.value as Consent["method"] })}>
                <option value="signed_form">Signed form</option>
                <option value="email">Email</option>
                <option value="online">Online form</option>
                <option value="other">Other</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="ref">Where the record is kept</label>
              <input id="ref" value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })}
                placeholder="e.g. secretariat file 2026/14" />
            </div>
          </div>
          <p className="muted small">
            Record exactly what the finalist signed. Unticking a part records a withdrawal; earlier records are kept.
          </p>
          <div className="inline-form">
            <button type="submit">Save</button>
            <button type="button" className="secondary" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {error && <div className="notice error">{error}</div>}
    </section>
  );
}
