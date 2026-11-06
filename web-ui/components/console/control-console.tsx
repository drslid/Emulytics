"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../lib/client-api";
import type { Data, Device, Page, Run, RunDetail as Detail, Summary, User, View, Workflow } from "../../lib/console-types";
import { Icon } from "./icons";
import { BrandMark } from "./brand-mark";
import { ErrorNotice } from "./shared";
import { Overview } from "./overview";
import { Devices } from "./devices";
import { Workflows } from "./workflows";
import { Activity } from "./activity";
import { Security } from "./security";
import { DeviceForm } from "./device-form";
import { RunDialog } from "./run-dialog";
import { RunDetail } from "./run-detail";

const navigation = [
  { id: "overview", href: "/", label: "Vue d’ensemble", icon: "overview" as const },
  { id: "devices", href: "/telephones", label: "Téléphones", icon: "phone" as const },
  { id: "workflows", href: "/automatisations", label: "Automatisations", icon: "workflow" as const },
  { id: "activity", href: "/activite", label: "Activité", icon: "activity" as const }
];
const titles: Record<View, { title: string; subtitle: string }> = {
  overview: { title: "Tour de contrôle", subtitle: "Votre flotte et vos automatisations, au même endroit." },
  devices: { title: "Téléphones", subtitle: "Sélectionnez les appareils que vous souhaitez piloter." },
  workflows: { title: "Automatisations", subtitle: "Des parcours reproductibles, pour un ou plusieurs téléphones." },
  activity: { title: "Activité", subtitle: "Suivez les exécutions et retrouvez leurs résultats." },
  security: { title: "Sécurité", subtitle: "Votre compte et les protections de votre espace." }
};
export function ControlConsole({ user, view }: { user: User; view: View }) {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [offset, setOffset] = useState(0);
  const [runOffset, setRunOffset] = useState(0);
  const [loadedOffsets, setLoadedOffsets] = useState({ devices: 0, runs: 0 });
  const [selected, setSelected] = useState<string[]>([]);
  const [adding, setAdding] = useState(false);
  const [launching, setLaunching] = useState<{ workflow?: Workflow; ids: string[] } | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const pending = useRef(false);
  const sequence = useRef(0);
  const load = useCallback(async () => {
    const request = ++sequence.current;
    pending.current = true; setRefreshing(true);
    try {
      const [fleet, workflows, runs, summary] = await Promise.all([
        api<Page<Device>>(`console/fleet?limit=100&offset=${offset}`), api<Page<Workflow>>("workflows?limit=100&offset=0"),
        api<Page<Run>>(`runs?limit=100&offset=${runOffset}`), api<Summary>("console/summary")
      ]);
      if (request !== sequence.current) return;
      setData({ devices: fleet.items, devicesTotal: fleet.total ?? fleet.items.length, workflows: workflows.items, runs: runs.items, summary });
      setLoadedOffsets({ devices: offset, runs: runOffset });
      setSelected((current) => current.filter((id) => !fleet.items.some((device) => device.device_id === id && device.availability === "needs_review")));
      setUpdatedAt(new Date()); setError("");
    } catch (failure) { if (request === sequence.current) setError((failure as Error).message); }
    finally { if (request === sequence.current) { pending.current = false; setRefreshing(false); } }
  }, [offset, runOffset]);
  useEffect(() => {
    void load();
    const timer = setInterval(() => { if (!pending.current && document.visibilityState === "visible") void load(); }, 5000);
    const visible = () => { if (document.visibilityState === "visible" && !pending.current) void load(); };
    document.addEventListener("visibilitychange", visible);
    return () => { clearInterval(timer); document.removeEventListener("visibilitychange", visible); sequence.current += 1; };
  }, [load]);
  async function logout() {
    try { await api("auth/logout", {}); window.location.assign("/connexion"); }
    catch (failure) { setError((failure as Error).message); }
  }
  function launched(run: Detail) {
    setLaunching(null); setSelected([]); setRunId(run.id);
    setNotice("Exécution enregistrée. Le worker la prendra en charge sur les téléphones ciblés."); void load();
  }
  const title = titles[view];
  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Aller au contenu</a>
    <aside className="app-sidebar">
      <a className="app-brand" href="/" aria-label="Emulytix, vue d’ensemble"><BrandMark /><span>Emulytix<span className="brand-caption">Console opérateur</span></span></a>
      <nav className="main-navigation" aria-label="Navigation principale">{navigation.map((item) => <a key={item.id} href={item.href} aria-current={view === item.id ? "page" : undefined} className={view === item.id ? "nav-item nav-item--active" : "nav-item"}><Icon name={item.icon} /><span>{item.label}</span>{item.id === "activity" && !!data?.summary.runs_needs_review && <span className="nav-count">{data.summary.runs_needs_review}</span>}</a>)}</nav>
      <div className="sidebar-bottom"><a href="/validation" className="nav-item"><Icon name="archive" /><span>Banc de validation</span></a><a href="/securite" className={view === "security" ? "nav-item nav-item--active" : "nav-item"} aria-current={view === "security" ? "page" : undefined}><Icon name="shield" /><span>Sécurité</span></a><div className="sidebar-account"><span className="avatar">{user.username.slice(0, 1).toUpperCase()}</span><div><strong>{user.username}</strong><span>Accès vérifié</span></div><button className="icon-button" onClick={() => void logout()} aria-label="Se déconnecter"><Icon name="logout" size={18} /></button></div></div>
    </aside>
    <div className="app-main"><header className="topbar"><div><span className="workspace-indicator" />Espace de travail<span className="topbar-separator">/</span><strong>{view === "overview" ? "Vue d’ensemble" : title.title}</strong></div><span className="topbar-security"><Icon name="shield" size={16} />Accès vérifié</span></header>
      <main id="main-content" className="console-content" tabIndex={-1}>
        <div className="page-heading"><div><h1>{title.title}</h1><p>{title.subtitle}</p></div>{view !== "security" && <button className="button button--primary" disabled={!data} onClick={() => setLaunching({ ids: [] })}><Icon name="plus" size={19} />Lancer une automatisation</button>}</div>
        {view !== "security" && <div className="refresh-line"><span className={`connection-dot ${error ? "connection-dot--offline" : ""}`} /><span>{error ? "Actualisation interrompue · dernières données conservées" : updatedAt ? `Mis à jour à ${new Intl.DateTimeFormat("fr-FR", { timeStyle: "short" }).format(updatedAt)}` : "Connexion au service…"}</span><button className="text-button" disabled={refreshing} onClick={() => void load()}><Icon name="refresh" size={15} />{refreshing ? "Actualisation…" : "Actualiser"}</button></div>}
        {error && <ErrorNotice message={error} />}
        {notice && <div className="notice notice--success" role="status"><Icon name="check" /><span>{notice}</span><button className="icon-button" onClick={() => setNotice("")} aria-label="Masquer la confirmation"><Icon name="close" size={17} /></button></div>}
        {view === "security" ? <Security user={user} onLogout={() => void logout()} /> : !data ? <section className="surface loading-state" aria-busy={!error} role="status">{error ? <><h2>La console ne peut pas charger vos données</h2><p>Vos données restent conservées. Réessayez lorsque le service est disponible.</p><button className="button button--secondary" onClick={() => void load()} disabled={refreshing}>Réessayer</button></> : <><div className="skeleton-line" /><div className="skeleton-line skeleton-line--short" /><p>Chargement de votre espace…</p></>}</section> : <>
          {view === "overview" && <Overview data={data} onOpen={setRunId} onLaunch={() => setLaunching({ ids: [] })} onAdd={() => setAdding(true)} />}
          {view === "devices" && <Devices devices={data.devices} total={data.devicesTotal} offset={loadedOffsets.devices} onPage={(value) => { setOffset(value); setSelected([]); }} selected={selected} onSelect={setSelected} onAdd={() => setAdding(true)} onLaunch={() => setLaunching({ ids: [...selected] })} />}
          {view === "workflows" && <Workflows workflows={data.workflows} onLaunch={(workflow) => setLaunching({ workflow, ids: [] })} />}
          {view === "activity" && <Activity runs={data.runs} total={data.summary.runs_total} offset={loadedOffsets.runs} onPage={setRunOffset} onOpen={setRunId} onLaunch={() => setLaunching({ ids: [] })} />}
        </>}
      </main>
    </div>
    {adding && <DeviceForm onClose={() => setAdding(false)} onAdded={() => { setAdding(false); setNotice("Téléphone ajouté. Sa connexion reste à vérifier sur le worker."); void load(); }} />}
    {launching && data && <RunDialog userId={user.id} devices={data.devices} workflows={data.workflows} initialWorkflow={launching.workflow} initialDeviceIds={launching.ids} onClose={() => setLaunching(null)} onLaunched={launched} />}
    {runId && <RunDetail key={runId} runId={runId} onClose={() => setRunId(null)} onChanged={() => void load()} />}
  </div>;
}
