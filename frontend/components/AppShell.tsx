"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  IconBook,
  IconCheck,
  IconChevron,
  IconClipboard,
  IconDashboard,
  IconDocument,
  IconFolder,
  IconGear,
  IconMenu,
  IconPeople,
  IconPerson,
  IconRanking,
  IconShield,
  IconSparkle,
} from "@/components/Icons";
import Logo from "@/components/Logo";
import { api, ApiError, initials, type Me, ROLE_LABELS, SESSION_CHANNEL } from "@/lib/api";

const PUBLIC = ["/login", "/accept-invite"];

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ size?: number }>;
  match: (path: string) => boolean;
  show?: (me: Me) => boolean;
};

const NAV: NavItem[] = [
  { href: "/", label: "Dashboard", icon: IconDashboard, match: (p) => p === "/" },
  { href: "/finalists", label: "Finalists", icon: IconPerson, match: (p) => p === "/finalists" || p.includes("/finalists/") },
  { href: "/rankings", label: "AI Rankings", icon: IconRanking, match: (p) => p.startsWith("/rankings") || p.startsWith("/calibration") },
  { href: "/knowledge-base", label: "Knowledge Base", icon: IconBook, match: (p) => p.startsWith("/knowledge-base") },
  {
    href: "/categories",
    label: "Award Categories",
    icon: IconFolder,
    match: (p) => p === "/categories" || (p.startsWith("/categories/") && !p.includes("/finalists/")),
  },
  { href: "/judges-pack", label: "Judges' Pack", icon: IconClipboard, match: (p) => p.startsWith("/judges-pack") },
  { href: "/judges-scores", label: "Judges' Scores", icon: IconCheck, match: (p) => p.startsWith("/judges-scores"), show: (me) => me.permissions.view_judge_scores },
  { href: "/reports", label: "Reports", icon: IconDocument, match: (p) => p.startsWith("/reports") },
  { href: "/admin/users", label: "Users", icon: IconPeople, match: (p) => p.startsWith("/admin/users"), show: (me) => me.permissions.manage_users },
  { href: "/admin/roles", label: "Roles & Rights", icon: IconShield, match: (p) => p.startsWith("/admin/roles"), show: (me) => me.permissions.manage_users },
  { href: "/admin/costs", label: "AI Costs", icon: IconSparkle, match: (p) => p.startsWith("/admin/costs"), show: (me) => me.permissions.manage_users },
  { href: "/account", label: "Settings", icon: IconGear, match: (p) => p.startsWith("/account") },
];

/** A profile in silhouette, facing left (decoration only). */
function Profile({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 100 140" className={className} aria-hidden preserveAspectRatio="xMidYMax meet">
      <circle cx="80" cy="24" r="13" />
      <path d="M60 10C40 10 30 25 31 40c0 6-3 10-7 16-2 3 0 5 3 5l1 5c-1 3 1 5 3 5-1 3 0 6 3 7 2 6 8 8 16 7l2 15c-12 4-22 12-28 40h76V60c0-30-15-50-40-50z" />
    </svg>
  );
}

function UserMenu({ me }: { me: Me }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  async function signOut() {
    try {
      await api.logout();
    } finally {
      // Sign out every other open tab too, and replace this page in the history so Back
      // doesn't return to it.
      new BroadcastChannel(SESSION_CHANNEL).postMessage("signed-out");
      window.location.replace("/login");
    }
  }

  const role = ROLE_LABELS[me.role as keyof typeof ROLE_LABELS] ?? me.role;
  return (
    <div className="user-menu" ref={ref}>
      <button className="user-button" onClick={() => setOpen(!open)} aria-expanded={open} aria-haspopup="menu">
        <span className="avatar small">{initials(me.display_name)}</span>
        <span className="user-name">{me.display_name}</span>
        <IconChevron dir="down" size={16} />
      </button>
      {open && (
        <div className="user-dropdown" role="menu">
          <div className="user-dropdown-head">
            <strong>{me.display_name}</strong>
            <span className="muted small">
              {role} · {me.email}
            </span>
          </div>
          <Link href="/account" role="menuitem" onClick={() => setOpen(false)}>
            Account and security
          </Link>
          {me.permissions.manage_users && (
            <Link href="/admin/users" role="menuitem" onClick={() => setOpen(false)}>
              Manage users
            </Link>
          )}
          <button className="link" role="menuitem" onClick={signOut}>
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isPublic = PUBLIC.includes(pathname);
  // Nothing behind sign-in is shown until the server confirms the session.
  const [me, setMe] = useState<Me | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    if (isPublic) return setMe(null);
    const verify = () =>
      api.me().then(
        (user) => {
          setUnreachable(false);
          setMe(user);
        },
        // A 401 sends the browser to sign in (lib/api.ts); anything else, say so.
        (e) => !(e instanceof ApiError && e.status === 401) && setUnreachable(true),
      );
    verify();
    // Back and Forward can restore a page from the browser's memory: hide it and check the
    // session again, so a signed-out session never shows a page.
    const restored = (e: PageTransitionEvent) => {
      if (!e.persisted) return;
      setMe(null);
      verify();
    };
    // Coming back to the tab after the session expired or was ended elsewhere.
    const visible = () => document.visibilityState === "visible" && verify();
    const channel = new BroadcastChannel(SESSION_CHANNEL);
    channel.onmessage = (e) => {
      if (e.data !== "signed-out") return;
      setMe(null);
      window.location.replace("/login");
    };
    window.addEventListener("pageshow", restored);
    document.addEventListener("visibilitychange", visible);
    return () => {
      window.removeEventListener("pageshow", restored);
      document.removeEventListener("visibilitychange", visible);
      channel.close();
    };
  }, [isPublic]);
  useEffect(() => setNavOpen(false), [pathname]);

  if (isPublic || !me) {
    return (
      <div className="public-shell">
        <div className="public-brand">
          <Logo />
        </div>
        <main className="public-main">
          {isPublic ? (
            children
          ) : unreachable ? (
            <div className="card auth-card">
              <p>The server can&apos;t be reached right now.</p>
              <button onClick={() => window.location.reload()}>Try again</button>
            </div>
          ) : (
            <p className="muted">Checking your session…</p>
          )}
        </main>
      </div>
    );
  }

  return (
    <div className={`shell${navOpen ? " nav-open" : ""}`}>
      <aside className="sidebar">
        <Link href="/" className="sidebar-brand" aria-label="Women on Boards Awards: dashboard">
          <Logo />
        </Link>
        <nav aria-label="Main">
          {NAV.filter((item) => !item.show || (me && item.show(me))).map((item) => {
            const active = item.match(pathname);
            const Icon = item.icon;
            return (
              <Link key={item.href} href={item.href} className={`nav-item${active ? " active" : ""}`} aria-current={active ? "page" : undefined}>
                <Icon size={20} />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
        <Profile className="sidebar-art" />
      </aside>
      <button className="nav-scrim" aria-label="Close menu" onClick={() => setNavOpen(false)} tabIndex={navOpen ? 0 : -1} />

      <div className="shell-main">
        <header className="banner">
          <button className="nav-toggle" aria-label="Open menu" onClick={() => setNavOpen(true)}>
            <IconMenu size={22} />
          </button>
          <div className="banner-titles">
            <div className="banner-title">Women on Boards Awards</div>
            <div className="banner-subtitle">AI-Powered Evaluation and Ranking System</div>
          </div>
          <div className="banner-art" aria-hidden>
            <span className="ribbon r1" />
            <span className="ribbon r2" />
            <Profile className="banner-profile p1" />
            <Profile className="banner-profile p2" />
            <Profile className="banner-profile p3" />
          </div>
          <UserMenu me={me} />
        </header>
        <main className="content">{children}</main>
        <footer className="site-footer">
          AI rankings are advisory. The awards committee retains responsibility for final deliberation and winner
          approval.
        </footer>
      </div>
    </div>
  );
}
