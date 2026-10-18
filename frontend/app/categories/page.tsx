"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { IconFolder } from "@/components/Icons";
import { api, type Category, slugify } from "@/lib/api";

export default function CategoriesPage() {
  const [categories, setCategories] = useState<Category[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(() => {
    api.listCategories().then(setCategories, (e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Award categories</h1>
          <p className="muted" style={{ margin: 0 }}>
            Choose a category to manage its finalists, rubric, assessment, ranking and reports.
          </p>
        </div>
        {!showForm && <button onClick={() => setShowForm(true)}>New category</button>}
      </div>

      {showForm && (
        <NewCategoryForm
          onCancel={() => setShowForm(false)}
          onCreated={() => {
            setShowForm(false);
            load();
          }}
        />
      )}

      {error && <div className="notice error">{error}</div>}
      {categories === null && !error && <p className="muted">Loading…</p>}
      {categories?.length === 0 && (
        <div className="card empty">No categories yet. Create the first award category.</div>
      )}

      <div className="grid">
        {categories?.map((c) => (
          <Link key={c.id} href={`/categories/${c.id}`} className="tile">
            <span className="tile-icon" aria-hidden>
              <IconFolder size={20} />
            </span>
            <h3>{c.name}</h3>
            {c.description && <div className="muted small">{c.description}</div>}
            <div className="stats">
              <span>
                <strong>{c.finalist_count}</strong> candidate{c.finalist_count === 1 ? "" : "s"}
              </span>
              <span>
                <strong>{c.document_count}</strong> document{c.document_count === 1 ? "" : "s"}
              </span>
            </div>
          </Link>
        ))}
      </div>
    </>
  );
}

function NewCategoryForm({ onCreated, onCancel }: { onCreated: () => void; onCancel: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const code = slugify(name);
    if (!code) return setError("Enter a category name.");
    setBusy(true);
    setError(null);
    try {
      await api.createCategory({ code, name: name.trim(), description: description.trim() || undefined });
      onCreated();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h2>New award category</h2>
      <div className="form-row">
        <div className="field">
          <label htmlFor="cat-name">Category name</label>
          <input id="cat-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus required />
        </div>
        <div className="field" style={{ flexBasis: 320 }}>
          <label htmlFor="cat-desc">Description (optional)</label>
          <input id="cat-desc" value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <button type="submit" disabled={busy}>{busy ? "Creating…" : "Create"}</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
      {error && <div className="notice error">{error}</div>}
    </form>
  );
}
