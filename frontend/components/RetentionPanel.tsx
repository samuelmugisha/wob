"use client";

import { useEffect, useState } from "react";
import { api, type Me } from "@/lib/api";

/** When this category's personal data is destroyed (Act s.18). Admins set it. */
export default function RetentionPanel({ categoryId, me }: { categoryId: string; me: Me | null }) {
  const [until, setUntil] = useState<string | null | undefined>(undefined);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const isAdmin = me?.role === "admin";

  useEffect(() => {
    api.getRetention(categoryId).then((r) => {
      setUntil(r.retention_until);
      setDraft(r.retention_until ?? "");
    }, (e: Error) => setError(e.message));
  }, [categoryId]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    try {
      const result = await api.setRetention(categoryId, draft || null);
      setUntil(result.retention_until);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (until === undefined) return null;
  return (
    <section className="card">
      <h2>Data retention</h2>
      <p className="small" style={{ marginTop: -6 }}>
        {until
          ? `All personal data in this category is permanently destroyed after ${until}.`
          : "No retention date set. Set one once the committee has agreed the retention schedule."}{" "}
        <span className="muted">The nightly purge (make purge-expired) destroys expired categories.</span>
      </p>
      {isAdmin && (
        <form className="inline-form" onSubmit={save}>
          <input type="date" value={draft} onChange={(e) => setDraft(e.target.value)} style={{ maxWidth: 180 }} />
          <button type="submit" className="secondary">
            Save
          </button>
        </form>
      )}
      {error && <div className="notice error">{error}</div>}
    </section>
  );
}
