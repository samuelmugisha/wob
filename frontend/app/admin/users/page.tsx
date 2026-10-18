"use client";

import { useCallback, useEffect, useState } from "react";
import { api, formatDate, type Invitation, type Role, ROLE_LABELS, type UserAccount } from "@/lib/api";

const ROLES = Object.keys(ROLE_LABELS) as Role[];

function InviteLink({ invite, onClose }: { invite: Invitation; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const [showLink, setShowLink] = useState(!invite.email_sent);
  const link = invite.invite_link;
  const hours = invite.expires_in_hours;
  return (
    <div className={`notice ${invite.email_enabled && !invite.email_sent ? "warning" : "success"}`}>
      {invite.email_sent ? (
        <>
          <strong>Email sent to {invite.user.email}</strong> with a link to set their password. It works once
          and expires in {hours} hours.{" "}
          {!showLink && (
            <button type="button" className="link" onClick={() => setShowLink(true)}>
              Show the link
            </button>
          )}
        </>
      ) : invite.email_enabled ? (
        <>
          <strong>The email to {invite.user.email} could not be sent</strong> ({invite.email_error}). Send them
          this set-password link securely instead. It works once, expires in {hours} hours, and won&apos;t be shown
          again.
        </>
      ) : (
        <>
          <strong>Send this set-password link to the person securely.</strong> It works once, expires in {hours}{" "}
          hours, and won&apos;t be shown again. (Invitation emails are not set up.)
        </>
      )}
      {showLink && (
      <div className="inline-form">
        <input readOnly value={link} onFocus={(e) => e.target.select()} />
        <button
          type="button"
          onClick={() => navigator.clipboard.writeText(link).then(() => setCopied(true))}
        >
          {copied ? "Copied" : "Copy"}
        </button>
        <button type="button" className="secondary" onClick={onClose}>
          Done
        </button>
      </div>
      )}
      {!showLink && (
        <div className="inline-form">
          <button type="button" className="secondary" onClick={onClose}>
            Done
          </button>
        </div>
      )}
    </div>
  );
}

export default function UsersPage() {
  const [users, setUsers] = useState<UserAccount[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [invite, setInvite] = useState<Invitation | null>(null);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("judge");

  const load = useCallback(() => {
    api.listUsers().then(setUsers, (e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  async function act(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function create(event: React.FormEvent) {
    event.preventDefault();
    await act(async () => {
      setInvite(await api.createUser(email.trim(), name.trim(), role));
      setEmail("");
      setName("");
    });
  }

  return (
    <>
      <h1>Users</h1>
      <p className="muted">
        Invite people, set their role, and remove access. Changing a role or deactivating an account
        signs the person out immediately.
      </p>
      {invite && <InviteLink key={invite.invite_link} invite={invite} onClose={() => setInvite(null)} />}
      {error && <div className="notice error">{error}</div>}

      <form className="card" onSubmit={create}>
        <h2>Invite someone</h2>
        <div className="form-row">
          <div className="field">
            <label htmlFor="u-name">Name</label>
            <input id="u-name" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="u-email">Email</label>
            <input id="u-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="field" style={{ flexGrow: 0, flexBasis: 200 }}>
            <label htmlFor="u-role">Role</label>
            <select id="u-role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABELS[r]}
                </option>
              ))}
            </select>
          </div>
          <button type="submit">Send invitation</button>
        </div>
      </form>

      <section className="card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Person</th>
                <th>Role</th>
                <th>Status</th>
                <th>Last sign-in</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {users?.map((u) => (
                <tr key={u.id} className={u.is_active ? undefined : "withdrawn"}>
                  <td>
                    {u.display_name}
                    <div className="muted small">{u.email}</div>
                  </td>
                  <td>
                    <select
                      value={u.role}
                      disabled={!u.is_active}
                      onChange={(e) => act(() => api.updateUser(u.id, { role: e.target.value as Role }))}
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {ROLE_LABELS[r]}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="small">
                    {!u.is_active ? (
                      <span className="badge muted">Deactivated</span>
                    ) : !u.has_password ? (
                      <span className="badge warning">Invited</span>
                    ) : (
                      <span className="badge success">Active</span>
                    )}{" "}
                    {u.mfa_enabled && <span className="badge muted">2FA</span>}{" "}
                    {u.locked && <span className="badge danger">Locked</span>}
                  </td>
                  <td className="small">{u.last_login_at ? formatDate(u.last_login_at) : "—"}</td>
                  <td className="actions">
                    {u.is_active && (
                      <button
                        className="link"
                        onClick={() =>
                          act(async () => {
                            if (!window.confirm(`Send ${u.display_name} a new set-password link? Their current password and two-factor setup stop working.`)) return;
                            setInvite(await api.reissueInvite(u.id));
                          })
                        }
                      >
                        New link
                      </button>
                    )}
                    <button
                      className="link"
                      onClick={() =>
                        act(async () => {
                          if (u.is_active && !window.confirm(`Deactivate ${u.display_name}? They are signed out at once.`)) return;
                          await api.updateUser(u.id, { is_active: !u.is_active });
                        })
                      }
                    >
                      {u.is_active ? "Deactivate" : "Reactivate"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
