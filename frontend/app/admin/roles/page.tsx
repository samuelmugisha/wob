"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Role, ROLE_LABELS, type RolePermissions } from "@/lib/api";

type Granted = Partial<Record<Role, string[]>>;

function same(a: string[] = [], b: string[] = []): boolean {
  return a.length === b.length && a.every((p) => b.includes(p));
}

export default function RolesPage() {
  const [data, setData] = useState<RolePermissions | null>(null);
  const [granted, setGranted] = useState<Granted>({});
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.rolePermissions().then(
      (d) => {
        setData(d);
        setGranted(Object.fromEntries(d.groups.map((g) => [g.role, g.permissions])));
      },
      (e: Error) => setError(e.message),
    );
  }, []);
  useEffect(load, [load]);

  const changed = (data?.groups ?? []).filter((g) => !same(g.permissions, granted[g.role]));

  // Warn before leaving with changes that haven't been saved.
  useEffect(() => {
    if (changed.length === 0) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [changed.length]);

  function toggle(role: Role, key: string) {
    setSaved(false);
    setGranted((all) => {
      const current = all[role] ?? [];
      return { ...all, [role]: current.includes(key) ? current.filter((p) => p !== key) : [...current, key] };
    });
  }

  async function save() {
    const summary = changed.map((g) => ROLE_LABELS[g.role]).join(", ");
    if (!window.confirm(`Save the new rights for ${summary}? They apply to everyone in those groups at once.`)) return;
    setBusy(true);
    setError(null);
    try {
      for (const g of changed) await api.setRolePermissions(g.role, granted[g.role] ?? []);
      setSaved(true);
      load();
    } catch (e) {
      setError((e as Error).message);
      load();
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Roles &amp; rights</h1>
      <p className="muted">
        Choose what each user group may do. Administrators always hold every right, and only they can manage users,
        amend or unfreeze rubrics, set retention, purge data and hide categories. Every user can view categories,
        finalists, evidence and rankings. Changes apply at once and are recorded in the audit log.
      </p>
      {error && <div className="notice error">{error}</div>}
      {saved && changed.length === 0 && <div className="notice success">Rights saved.</div>}

      <section className="card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Right</th>
                <th className="num">{ROLE_LABELS.admin}</th>
                {data?.groups.map((g) => (
                  <th key={g.role} className="num">
                    {ROLE_LABELS[g.role]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data?.permissions.map((p) => (
                <tr key={p.key}>
                  <td>
                    {p.label}
                    <div className="muted small">{p.description}</div>
                  </td>
                  <td className="num">
                    <input type="checkbox" checked disabled aria-label={`${ROLE_LABELS.admin}: ${p.label}`} />
                  </td>
                  {data.groups.map((g) => (
                    <td key={g.role} className="num">
                      <input
                        type="checkbox"
                        checked={granted[g.role]?.includes(p.key) ?? false}
                        disabled={busy}
                        onChange={() => toggle(g.role, p.key)}
                        aria-label={`${ROLE_LABELS[g.role]}: ${p.label}`}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="inline-form">
          <button onClick={save} disabled={busy || changed.length === 0}>
            {busy ? "Saving…" : "Save changes"}
          </button>
          <button className="secondary" onClick={load} disabled={busy || changed.length === 0}>
            Discard changes
          </button>
          {changed.length > 0 && <span className="muted small">Unsaved changes</span>}
        </div>
      </section>
    </>
  );
}
