"use client";

import dynamic from "next/dynamic";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

const CommandOrb = dynamic(() => import("./components/command-orb"), {
  ssr: false,
  loading: () => <div className="orb-loading" />
});

type Lead = {
  id: string;
  business_name: string;
  industry?: string;
  city?: string;
  country?: string;
  qualification?: "A" | "B" | "C";
  lead_status?: string;
};

type Draft = {
  id: string;
  draft_type: string;
  approval_status: string;
  recipient?: string;
  subject?: string;
  body?: string;
  lead?: { business_name?: string } | null;
};

type ApiList<T> = { count?: number; items?: T[] };

const navItems = [
  { id: "overview", label: "Overview", icon: "◈" },
  { id: "campaign", label: "Campaign CRM", icon: "◎" },
  { id: "agents", label: "Agent fleet", icon: "✳" },
  { id: "stack", label: "Free stack", icon: "⌘" }
];

export default function HomePage() {
  const [authenticated, setAuthenticated] = useState(false);
  const [checking, setChecking] = useState(true);
  const [password, setPassword] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [error, setError] = useState("");
  const [leads, setLeads] = useState<Lead[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [loadingData, setLoadingData] = useState(false);
  const [selectedNav, setSelectedNav] = useState("overview");
  const [busyDraft, setBusyDraft] = useState("");

  const refresh = useCallback(async () => {
    setLoadingData(true);
    try {
      const [leadResponse, draftResponse] = await Promise.all([
        fetch("/api/backend/campaigns/content-agency/leads?limit=100", { cache: "no-store" }),
        fetch("/api/backend/campaigns/content-agency/drafts?limit=100", { cache: "no-store" })
      ]);

      if (leadResponse.status === 401 || draftResponse.status === 401) {
        setAuthenticated(false);
        setLeads([]);
        setDrafts([]);
        return;
      }
      if (!leadResponse.ok || !draftResponse.ok) {
        throw new Error("Backend CRM could not be reached. Check its URL and server secrets.");
      }

      const leadData = await leadResponse.json() as ApiList<Lead>;
      const draftData = await draftResponse.json() as ApiList<Draft>;
      setLeads(leadData.items ?? []);
      setDrafts(draftData.items ?? []);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load campaign data.");
    } finally {
      setLoadingData(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    fetch("/api/auth/session", { cache: "no-store" })
      .then(async (response) => response.ok ? response.json() as Promise<{ authenticated: boolean }> : { authenticated: false })
      .then((result) => {
        if (!active) return;
        setAuthenticated(result.authenticated);
        setChecking(false);
        if (result.authenticated) void refresh();
      })
      .catch(() => {
        if (active) setChecking(false);
      });
    return () => { active = false; };
  }, [refresh]);

  const gradeA = useMemo(() => leads.filter((lead) => lead.qualification === "A").length, [leads]);
  const pendingDrafts = useMemo(
    () => drafts.filter((draft) => draft.approval_status === "awaiting_approval"),
    [drafts]
  );

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoginBusy(true);
    setError("");
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password })
      });
      const result = await response.json() as { error?: string; authenticated?: boolean };
      if (!response.ok) throw new Error(result.error ?? "Sign-in failed.");
      setAuthenticated(true);
      setPassword("");
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Sign-in failed.");
    } finally {
      setLoginBusy(false);
    }
  }

  async function signOut() {
    await fetch("/api/auth/logout", { method: "POST" });
    setAuthenticated(false);
    setLeads([]);
    setDrafts([]);
  }

  async function approveForManualSend(draftId: string) {
    setBusyDraft(draftId);
    setError("");
    try {
      const response = await fetch(`/api/backend/campaigns/content-agency/drafts/${draftId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: true, note: "Reviewed in the private command centre; approval is for manual sending only." })
      });
      const result = await response.json() as { error?: string };
      if (!response.ok) throw new Error(result.error ?? "Could not record approval.");
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Approval failed.");
    } finally {
      setBusyDraft("");
    }
  }

  const openSection = (id: string) => {
    setSelectedNav(id);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <a className="brand-lockup" href="#overview" onClick={() => setSelectedNav("overview")}>
          <span className="brand-mark"><span /></span>
          <span><strong>UNIVERSAL</strong><small>AI EMPIRE / CONTROL</small></span>
        </a>

        <div className="workspace-label">WORKSPACE <span>01</span></div>
        <nav className="main-nav" aria-label="Main navigation">
          {navItems.map((item) => (
            <button
              className={selectedNav === item.id ? "nav-item active" : "nav-item"}
              key={item.id}
              onClick={() => openSection(item.id)}
              type="button"
            >
              <span className="nav-icon">{item.icon}</span>
              {item.label}
              {item.id === "campaign" && authenticated && <span className="nav-count">{leads.length}</span>}
            </button>
          ))}
        </nav>

        <div className="sidebar-spacer" />
        <div className="sidebar-runtime">
          <span className="runtime-light" />
          <div><strong>Cost-aware mode</strong><small>Free tiers first · no auto-spend</small></div>
        </div>
        <div className="sidebar-footer">
          <span className="avatar">AI</span>
          <span><strong>Workspace owner</strong><small>{authenticated ? "Private session active" : "Sign in to unlock CRM"}</small></span>
          {authenticated && <button className="logout-button" type="button" onClick={signOut} aria-label="Sign out">↗</button>}
        </div>
      </aside>

      <section className="main-column">
        <header className="topbar">
          <div className="breadcrumbs"><span>COMMAND</span><i>/</i><strong>{navItems.find((item) => item.id === selectedNav)?.label ?? "Overview"}</strong></div>
          <div className="topbar-right">
            <span className="topbar-date">04 NOV 2026</span>
            <span className={authenticated ? "session-pill live" : "session-pill"}><span />{authenticated ? "PRIVATE SESSION" : "LOCKED VIEW"}</span>
            <button className="icon-button" type="button" onClick={() => authenticated && void refresh()} aria-label="Refresh data" disabled={!authenticated || loadingData}>↻</button>
          </div>
        </header>

        <div className="content-wrap">
          <section className="hero-panel" id="overview">
            <div className="hero-copy">
              <div className="eyebrow"><span className="eyebrow-dot" /> THE OPERATING LAYER <span className="eyebrow-line" /></div>
              <h1>Build momentum.<br /><em>Stay in control.</em></h1>
              <p className="hero-description">One calm command layer for research, content, client acquisition and a growing network of specialist AI workflows.</p>
              <div className="hero-actions">
                <button className="primary-button" onClick={() => openSection("campaign")} type="button">Open campaign <span>↗</span></button>
                <button className="ghost-button" onClick={() => openSection("agents")} type="button">Explore the fleet</button>
              </div>
              <div className="hero-footnote"><span className="mini-check">✓</span> HUMAN APPROVAL FOR EXTERNAL ACTIONS</div>
            </div>
            <div className="hero-visual">
              <div className="orbit-label orbit-label-one"><i /> INTELLIGENCE CORE</div>
              <div className="orbit-label orbit-label-two">120 <span>ROLE BLUEPRINTS</span></div>
              <CommandOrb />
              <div className="orb-readout"><span>SYS / 01</span><b>AI</b><span>ORCHESTRATION</span></div>
            </div>
            <div className="hero-index">01 — 04</div>
          </section>

          <section className="metrics-grid" aria-label="System metrics">
            <article className="metric-card">
              <div className="metric-head"><span>AGENT BLUEPRINTS</span><b>↗</b></div>
              <div className="metric-value">120</div>
              <div className="metric-caption"><span className="metric-signal" /> On-demand role templates</div>
              <div className="metric-line"><i style={{ width: "82%" }} /></div>
            </article>
            <article className="metric-card">
              <div className="metric-head"><span>DEPARTMENTS</span><b>⌘</b></div>
              <div className="metric-value">12</div>
              <div className="metric-caption">Specialist workstreams</div>
              <div className="metric-line"><i style={{ width: "68%" }} /></div>
            </article>
            <article className="metric-card">
              <div className="metric-head"><span>PUBLIC LEADS</span><b>◎</b></div>
              <div className="metric-value">{authenticated ? leads.length : "—"}</div>
              <div className="metric-caption">{authenticated ? `${gradeA} high-fit · ${leads.length - gradeA} review` : "Private CRM · sign in to view"}</div>
              <div className="metric-line"><i style={{ width: authenticated ? `${Math.min(leads.length * 5, 100)}%` : "9%" }} /></div>
            </article>
            <article className="metric-card accent-card">
              <div className="metric-head"><span>APPROVAL QUEUE</span><b>◷</b></div>
              <div className="metric-value">{authenticated ? pendingDrafts.length : "—"}</div>
              <div className="metric-caption">{authenticated ? "Drafts awaiting review" : "No outbound actions run"}</div>
              <div className="metric-line"><i style={{ width: authenticated ? `${Math.min(pendingDrafts.length * 7, 100)}%` : "12%" }} /></div>
            </article>
          </section>

          {error && <div className="notice error-notice" role="alert"><span>!</span>{error}<button type="button" onClick={() => setError("")}>Dismiss</button></div>}

          <section className="mid-grid">
            <article className="panel campaign-panel" id="campaign">
              <div className="panel-heading">
                <div><div className="eyebrow small-eyebrow">GROWTH ENGINE / 01</div><h2>Client acquisition</h2></div>
                <span className="panel-index">CAMPAIGN 001</span>
              </div>
              <div className="campaign-highlight">
                <div className="campaign-symbol">✳</div>
                <div className="campaign-info"><strong>International content agency</strong><span>London · Dubai · global prospects</span></div>
                <span className="campaign-state"><i /> {authenticated ? "CRM CONNECTED" : "PRIVATE DATA"}</span>
              </div>
              <div className="campaign-numbers">
                <div><strong>{authenticated ? leads.filter((lead) => lead.qualification === "A").length : "—"}</strong><span>A-GRADE</span></div>
                <div><strong>{authenticated ? leads.length : "—"}</strong><span>PROSPECTS</span></div>
                <div><strong>{authenticated ? pendingDrafts.length : "—"}</strong><span>TO REVIEW</span></div>
              </div>
              {authenticated ? (
                <div className="lead-list">
                  {leads.slice(0, 4).map((lead) => (
                    <div className="lead-row" key={lead.id}>
                      <span className="lead-avatar">{lead.business_name.slice(0, 1).toUpperCase()}</span>
                      <span className="lead-name"><strong>{lead.business_name}</strong><small>{[lead.city, lead.country].filter(Boolean).join(" · ")}</small></span>
                      <span className={lead.qualification === "A" ? "grade grade-a" : "grade"}>{lead.qualification ?? "B"}</span>
                      <span className="lead-status">{lead.lead_status?.replaceAll("_", " ") ?? "qualified"}</span>
                    </div>
                  ))}
                  {leads.length === 0 && <div className="empty-state">No prospects have been imported to this campaign yet.</div>}
                </div>
              ) : (
                <div className="locked-preview"><span className="lock-symbol">⌑</span><p>Lead names, emails and proposals stay private. Sign in to inspect the live CRM.</p></div>
              )}
              <button className="text-action" type="button" onClick={() => openSection("campaign")}>View campaign workspace <span>→</span></button>
            </article>

            <article className="panel approval-panel">
              <div className="panel-heading">
                <div><div className="eyebrow small-eyebrow">HUMAN CHECKPOINT</div><h2>Review queue</h2></div>
                <span className="queue-count">{authenticated ? String(pendingDrafts.length).padStart(2, "0") : "—"}</span>
              </div>
              <p className="panel-subtitle">Every external message remains a draft until you review it.</p>
              {authenticated ? (
                <div className="draft-list">
                  {pendingDrafts.slice(0, 3).map((draft) => (
                    <div className="draft-row" key={draft.id}>
                      <div className="draft-type">{draft.draft_type.replaceAll("_", " ")}</div>
                      <strong>{draft.lead?.business_name ?? draft.recipient ?? "Campaign prospect"}</strong>
                      <span>{draft.subject || "Storyboard / sample concept"}</span>
                      {draft.draft_type === "first_touch" && (
                        <button
                          className="approve-button"
                          type="button"
                          disabled={busyDraft === draft.id}
                          onClick={() => void approveForManualSend(draft.id)}
                        >
                          {busyDraft === draft.id ? "Saving…" : "Approve for manual send"}
                        </button>
                      )}
                    </div>
                  ))}
                  {pendingDrafts.length === 0 && <div className="empty-state">Nothing is waiting for approval.</div>}
                </div>
              ) : (
                <div className="locked-preview approval-locked"><span className="lock-symbol">⌑</span><p>Sign in to inspect individual drafts. Approval only records your decision; it never sends a message.</p></div>
              )}
              <div className="approval-foot"><span className="shield-icon">⬡</span><span>NO EMAILS, DMS OR FORMS ARE SENT BY THIS DASHBOARD.</span></div>
            </article>
          </section>

          <section className="lower-grid">
            <article className="panel fleet-panel" id="agents">
              <div className="panel-heading">
                <div><div className="eyebrow small-eyebrow">SPECIALIST NETWORK</div><h2>12 departments</h2></div>
                <span className="panel-index">ON-DEMAND</span>
              </div>
              <div className="department-grid">
                {[
                  ["01","YouTube automation","15"],
                  ["02","Freelance agency","12"],
                  ["03","Content studio","10"],
                  ["04","Affiliate systems","10"],
                  ["05","AI SaaS","10"],
                  ["06","E-commerce","10"],
                  ["07","Sales & growth","10"],
                  ["08","Research","10"],
                  ["09","Media production","10"],
                  ["10","Operations","8"],
                  ["11","Finance","7"],
                  ["12","Quality & risk","8"]
                ].map(([number, label, count]) => (
                  <div className="department-row" key={number}>
                    <span>{number}</span><strong>{label}</strong><small>{count} roles</small>
                  </div>
                ))}
              </div>
              <p className="fine-print">These are role templates, not 120 continuously running agents. Workers start only when configured and dispatched.</p>
            </article>

            <article className="panel stack-panel" id="stack">
              <div className="panel-heading">
                <div><div className="eyebrow small-eyebrow">INFRASTRUCTURE / FREE-FIRST</div><h2>Technology stack</h2></div>
                <span className="free-badge">FREE CORE</span>
              </div>
              <div className="stack-item"><span className="stack-icon teal">Py</span><div><strong>FastAPI · Python</strong><small>Backend control plane</small></div><span className="stack-status">RAILWAY</span></div>
              <div className="stack-item"><span className="stack-icon violet">Pg</span><div><strong>PostgreSQL · Supabase</strong><small>Private CRM and approval records</small></div><span className="stack-status">FREE PLAN</span></div>
              <div className="stack-item"><span className="stack-icon gold">3D</span><div><strong>Three.js · React Three Fiber</strong><small>Procedural 3D interface</small></div><span className="stack-status">OPEN SOURCE</span></div>
              <div className="stack-item"><span className="stack-icon blue">AI</span><div><strong>Free model tiers</strong><small>Optional, quota-limited providers</small></div><span className="stack-status">NOT CONNECTED</span></div>
              <div className="stack-warning"><span>!</span><p>Free-tier model capacity is limited. No GPU worker or paid API is assumed to be available.</p></div>
            </article>
          </section>

          <footer className="page-footer">
            <span>UNIVERSAL AI EMPIRE <i>·</i> PRIVATE COMMAND CENTRE</span>
            <span>BUILT FOR CONTROL, NOT AUTOPILOT CHAOS <b>✳</b></span>
          </footer>
        </div>
      </section>

      {!authenticated && (
        <div className="login-dock" role="dialog" aria-label="Private dashboard sign in">
          <div className="login-accent" />
          <div className="login-copy"><span className="eyebrow small-eyebrow">PRIVATE ACCESS</span><strong>{checking ? "Checking session…" : "Unlock command centre"}</strong><small>Use the dashboard password configured for this deployment.</small></div>
          <form className="login-form" onSubmit={signIn}>
            <label className="sr-only" htmlFor="dashboard-password">Dashboard password</label>
            <input id="dashboard-password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Dashboard password" disabled={checking || loginBusy} />
            <button className="primary-button login-button" type="submit" disabled={checking || loginBusy || password.length === 0}>{loginBusy ? "Checking…" : "Sign in"} <span>→</span></button>
          </form>
        </div>
      )}
    </main>
  );
}
