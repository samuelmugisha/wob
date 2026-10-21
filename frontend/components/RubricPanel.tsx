"use client";

import { useState } from "react";
import { api, type CriterionInput, type Me, type Rubric } from "@/lib/api";

const STATUS_TEXT: Record<Rubric["status"], string> = {
  draft: "Draft: editable; rankings are practice only",
  approved: "Approved; freeze it to use for production ranking. Only an administrator can amend it",
  frozen: "Frozen: production rubric. Only an administrator can unfreeze it",
};

function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64);
}

function RubricEditor({ rubric, onSaved, onCancel }: { rubric: Rubric; onSaved: () => void; onCancel: () => void }) {
  const [weighting, setWeighting] = useState<Rubric["weighting"]>(rubric.weighting);
  const [notes, setNotes] = useState(rubric.notes ?? "");
  const [rows, setRows] = useState<CriterionInput[]>(
    rubric.criteria.map((c) => ({
      code: c.code,
      name: c.name,
      description: c.description,
      evidence_expectations: c.evidence_expectations ?? "",
      weight: c.weight ?? "",
    })),
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function update(i: number, patch: Partial<CriterionInput>) {
    setRows((all) => all.map((row, j) => (j === i ? { ...row, ...patch } : row)));
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.updateRubric(rubric.id, {
        weighting,
        notes: notes.trim() || null,
        criteria: rows.map((r) => ({
          code: r.code || slug(r.name),
          name: r.name.trim(),
          description: r.description.trim(),
          evidence_expectations: (r.evidence_expectations ?? "").toString().trim() || null,
          weight: weighting === "weighted" && r.weight !== "" ? Number(r.weight) : null,
        })),
      });
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="rubric-editor">
      <div className="form-row">
        <div className="field" style={{ flexGrow: 0, flexBasis: 220 }}>
          <label htmlFor="weighting">Weighting</label>
          <select id="weighting" value={weighting} onChange={(e) => setWeighting(e.target.value as Rubric["weighting"])}>
            <option value="equal">Equal (until the committee approves weights)</option>
            <option value="weighted">Weighted</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="rubric-notes">Notes</label>
          <input id="rubric-notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
      </div>
      {rows.map((row, i) => (
        <fieldset key={i} className="criterion-row">
          <legend>Criterion {i + 1}</legend>
          <div className="form-row">
            <div className="field">
              <label>Name</label>
              <input value={row.name} onChange={(e) => update(i, { name: e.target.value })} required />
            </div>
            {weighting === "weighted" && (
              <div className="field" style={{ flexGrow: 0, flexBasis: 100 }}>
                <label>Weight</label>
                <input
                  type="number"
                  min="0.001"
                  step="any"
                  value={row.weight ?? ""}
                  onChange={(e) => update(i, { weight: e.target.value })}
                  required
                />
              </div>
            )}
          </div>
          <div className="field">
            <label>Description</label>
            <textarea rows={2} value={row.description} onChange={(e) => update(i, { description: e.target.value })} required />
          </div>
          <div className="field">
            <label>Evidence expected</label>
            <textarea
              rows={2}
              value={(row.evidence_expectations ?? "").toString()}
              onChange={(e) => update(i, { evidence_expectations: e.target.value })}
            />
          </div>
          <button type="button" className="link small" onClick={() => setRows((all) => all.filter((_, j) => j !== i))}>
            Remove criterion
          </button>
        </fieldset>
      ))}
      <div className="inline-form">
        <button
          type="button"
          className="secondary"
          onClick={() => setRows((all) => [...all, { code: "", name: "", description: "", evidence_expectations: "" }])}
        >
          Add criterion
        </button>
        <button type="submit" disabled={busy || rows.length === 0}>
          {busy ? "Saving…" : rubric.status === "approved" ? "Save amendment" : "Save draft"}
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
      {error && <div className="notice error">{error}</div>}
    </form>
  );
}

/** The category's scoring rubric (spec §7): drafts, committee approval and freezing. */
export default function RubricPanel({
  categoryId,
  rubric,
  me,
  onChanged,
}: {
  categoryId: string;
  rubric: Rubric | null;
  me: Me | null;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canEdit = me?.permissions.manage_evidence ?? false;
  const canApprove = me?.permissions.approve_rubrics ?? false;
  const canAdminister = me?.permissions.administer_rubrics ?? false;

  function unfreeze(rubricId: string) {
    const reason = window.prompt(
      "Unfreeze this rubric? It returns to approved so an administrator can amend it, and new " +
        "rankings are practice rankings until it is frozen again. Reason (recorded in the audit log):",
    );
    if (reason === null) return;
    if (!reason.trim()) {
      setError("Give a reason for unfreezing the rubric.");
      return;
    }
    act(() => api.unfreezeRubric(rubricId, reason.trim()));
  }

  async function act(action: () => Promise<unknown>, confirmText?: string) {
    if (confirmText && !window.confirm(confirmText)) return;
    setError(null);
    try {
      await action();
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section className="card">
      <div className="toolbar">
        <h2 style={{ margin: 0 }}>Scoring rubric</h2>
        <div className="inline-form" style={{ marginTop: 0 }}>
          {canEdit && (!rubric || rubric.status !== "draft") && (
            <button className="secondary" onClick={() => act(() => api.createRubric(categoryId, { use_template: true }))}>
              {rubric ? "New draft version" : "Start from draft template"}
            </button>
          )}
          {canEdit && rubric?.status === "draft" && !editing && (
            <button className="secondary" onClick={() => setEditing(true)}>
              Edit draft
            </button>
          )}
          {canApprove && rubric?.status === "draft" && (
            <button
              onClick={() =>
                act(() => api.approveRubric(rubric.id), "Approve these criteria as the committee's rubric?")
              }
            >
              Approve
            </button>
          )}
          {canAdminister && rubric?.status === "approved" && !editing && (
            <button className="secondary" onClick={() => setEditing(true)}>
              Amend rubric
            </button>
          )}
          {canAdminister && rubric?.status === "frozen" && (
            <button className="secondary" onClick={() => unfreeze(rubric.id)}>
              Unfreeze
            </button>
          )}
          {canApprove && rubric?.status === "approved" && (
            <button
              onClick={() =>
                act(
                  () => api.freezeRubric(rubric.id),
                  "Freeze this rubric? It can no longer be changed, and rankings become production rankings.",
                )
              }
            >
              Freeze
            </button>
          )}
        </div>
      </div>
      {error && <div className="notice error">{error}</div>}
      {!rubric && <div className="empty">No rubric yet. Assessments need one.</div>}
      {rubric && (
        <>
          <div className={`notice ${rubric.status === "frozen" ? "success" : "warning"}`}>
            <strong>
              Version {rubric.version} · {STATUS_TEXT[rubric.status]}
            </strong>
            {rubric.notes && <div className="small">{rubric.notes}</div>}
            <div className="small">
              {rubric.weighting === "equal" ? "Equal weighting" : "Weighted scoring"} · official 1–5 scale
            </div>
          </div>
          {editing ? (
            <RubricEditor
              rubric={rubric}
              onCancel={() => setEditing(false)}
              onSaved={() => {
                setEditing(false);
                onChanged();
              }}
            />
          ) : (
            <ol className="criteria-list">
              {rubric.criteria.map((c) => (
                <li key={c.id}>
                  <strong>{c.name}</strong>
                  {rubric.weighting === "weighted" && c.weight && <span className="muted"> · weight {c.weight}</span>}
                  <div className="small">{c.description}</div>
                  {c.evidence_expectations && (
                    <div className="small muted">Evidence expected: {c.evidence_expectations}</div>
                  )}
                </li>
              ))}
            </ol>
          )}
        </>
      )}
    </section>
  );
}
