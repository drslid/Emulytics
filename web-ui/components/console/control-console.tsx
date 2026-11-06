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
import { useLocale, useT } from "../../lib/i18n";
import { LanguageSelector } from "../language-selector";
import { Schedules, ScheduleEditor } from "./schedules";
import { Monitor } from "./monitor";
import { Logs } from "./logs";
import { Users, Profile } from "./users";

const navigation = [
  { id: "overview", href: "/", label: "Tableau de bord", icon: "overview" as const },
  { id: "devices", href: "/telephones", label: "Appareils", icon: "phone" as const },
  { id: "workflows", href: "/automatisations", label: "Parcours", icon: "workflow" as const },
  { id: "activity", href: "/activite", label: "Exécutions", icon: "activity" as const },
  { id: "schedules", href: "/planifications", label: "Planifications", icon: "clock" as const },
  { id: "monitor", href: "/monitoring", label: "Monitoring", icon: "activity" as const },
  { id: "logs", href: "/journal", label: "Journal", icon: "archive" as const },
  { id: "users", href: "/utilisateurs", label: "Utilisateurs", icon: "users" as const }
];
const titles: Record<View, { title: string; subtitle: string }> = {
  overview: { title: "Tableau de bord", subtitle: "Votre flotte et vos automatisations, au même endroit." },
  devices: { title: "Appareils", subtitle: "Sélectionnez les appareils que vous souhaitez piloter." },
  workflows: { title: "Parcours", subtitle: "Des parcours reproductibles, pour un ou plusieurs téléphones." },
  activity: { title: "Exécutions", subtitle: "Suivez les exécutions et retrouvez leurs résultats." },
  schedules: { title: "Planifications", subtitle: "Choisissez quand lancer un parcours et sur quels appareils." },
  monitor: { title: "Monitoring", subtitle: "Toute l’architecture et son activité en temps réel." },
  logs: { title: "Journal", subtitle: "Les événements et les actions de votre espace." },
  users: { title: "Utilisateurs", subtitle: "Les comptes locaux, leurs rôles et leurs accès." },
  profile: { title: "Mon profil", subtitle: "Votre identité, votre rôle et vos préférences." },
  security: { title: "Sécurité", subtitle: "Votre compte et les protections de votre espace." }
};
export function ControlConsole({ user, view }: { user: User; view: View }) {
  const t = useT(); const { locale } = useLocale();
  const can = (permission: string) => user.permissions?.includes(permission) ?? false;
  const allowed = view !== "users" && view !== "logs" || can(view === "users" ? "users.manage" : "logs.read");
  const dataView = ["overview", "devices", "workflows", "activity", "schedules"].includes(view);
  const [scheduling, setScheduling] = useState<Workflow | null>(null);
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
    if (!dataView) return;
    void load();
    const timer = setInterval(() => { if (!pending.current && document.visibilityState === "visible") void load(); }, 5000);
    const visible = () => { if (document.visibilityState === "visible" && !pending.current) void load(); };
    document.addEventListener("visibilitychange", visible);
    return () => { clearInterval(timer); document.removeEventListener("visibilitychange", visible); sequence.current += 1; };
  }, [load, dataView]);
  async function logout() {
    try { await api("auth/logout", {}); window.location.assign("/connexion"); }
    catch (failure) { setError((failure as Error).message); }
  }
  function launched(run: Detail) {
    setLaunching(null); setSelected([]); setRunId(run.id);
    setNotice(t("Exécution enregistrée. Le worker la prendra en charge sur les téléphones ciblés.")); void load();
  }
  const title = titles[view];
  return <div className="app-shell">
    <a className="skip-link" href="#main-content">{t("Aller au contenu")}</a>
    <aside className="app-sidebar">
      <a className="app-brand" href="/" aria-label={t("Emulytix, tableau de bord")}><BrandMark /><span>Emulytix<span className="brand-caption">{t("Console opérateur")}</span></span></a>
      <nav className="main-navigation" aria-label={t("Navigation principale")}>{navigation.filter(item => item.id !== "users" && item.id !== "logs" || can(item.id === "users" ? "users.manage" : "logs.read")).map((item) => <a key={item.id} href={item.href} aria-current={view === item.id ? "page" : undefined} className={view === item.id ? "nav-item nav-item--active" : "nav-item"}><Icon name={item.icon} /><span>{t(item.label)}</span>{item.id === "activity" && !!data?.summary.runs_needs_review && <span className="nav-count">{data.summary.runs_needs_review}</span>}</a>)}</nav>
      <div className="sidebar-bottom"><a href="/profil" className={view === "profile" ? "nav-item nav-item--active" : "nav-item"}><Icon name="users" /><span>{t("Mon profil")}</span></a><a href="/securite" className={view === "security" ? "nav-item nav-item--active" : "nav-item"} aria-current={view === "security" ? "page" : undefined}><Icon name="shield" /><span>{t("Sécurité")}</span></a><div className="sidebar-account"><span className="avatar">{user.username.slice(0, 1).toUpperCase()}</span><div><strong>{user.username}</strong><span>{t({admin:"Admin",builder:"Builder",operator:"Operator",viewer:"Viewer",auditor:"Auditor"}[user.role])}</span></div><button className="icon-button" onClick={() => void logout()} aria-label={t("Se déconnecter")}><Icon name="logout" size={18} /></button></div></div>
    </aside>
    <div className="app-main"><header className="topbar"><div><span className="workspace-indicator" />{t("Espace de travail")}<span className="topbar-separator">/</span><strong>{t(title.title)}</strong></div><LanguageSelector /></header>
      <main id="main-content" className="console-content" tabIndex={-1}>
        <div className="page-heading"><div><h1>{t(title.title)}</h1><p>{t(title.subtitle)}</p></div>{dataView && view !== "devices" && view !== "workflows" && view !== "schedules" && can("runs.execute") && <button className="button button--primary" disabled={!data} onClick={() => setLaunching({ ids: [] })}><Icon name="plus" size={19} />{t("Lancer une automatisation")}</button>}</div>
        {dataView && <div className="refresh-line"><span className={`connection-dot ${error ? "connection-dot--offline" : ""}`} /><span>{error ? t("Actualisation interrompue · dernières données conservées") : updatedAt ? t("Mis à jour à {time}", { time: new Intl.DateTimeFormat(locale, { timeStyle: "short" }).format(updatedAt) }) : t("Connexion au service…")}</span><button className="text-button" disabled={refreshing} onClick={() => void load()}><Icon name="refresh" size={15} />{refreshing ? t("Actualisation…") : t("Actualiser")}</button></div>}
        {error && <ErrorNotice message={error} />}
        {notice && <div className="notice notice--success" role="status"><Icon name="check" /><span>{notice}</span><button className="icon-button" onClick={() => setNotice("")} aria-label={t("Masquer la confirmation")}><Icon name="close" size={17} /></button></div>}
        {!allowed ? <section className="surface empty-state"><Icon name="shield" size={32} /><h2>{t("Accès réservé")}</h2><p>{t("Votre rôle ne permet pas d’accéder à cette section.")}</p></section> : view === "profile" ? <Profile user={user} /> : view === "users" ? <Users user={user} /> : view === "monitor" ? <Monitor /> : view === "logs" ? <Logs /> : view === "security" ? <Security user={user} onLogout={() => void logout()} /> : !data ? <section className="surface loading-state" aria-busy={!error} role="status">{error ? <><h2>{t("La console ne peut pas charger vos données")}</h2><p>{t("Vos données restent conservées. Réessayez lorsque le service est disponible.")}</p><button className="button button--secondary" onClick={() => void load()} disabled={refreshing}>{t("Réessayer")}</button></> : <><div className="skeleton-line" /><div className="skeleton-line skeleton-line--short" /><p>{t("Chargement de votre espace…")}</p></>}</section> : <>
          {view === "overview" && <Overview data={data} onOpen={setRunId} onLaunch={() => setLaunching({ ids: [] })} onAdd={() => setAdding(true)} canAdd={can("devices.write")} canLaunch={can("runs.execute")} />}
          {view === "devices" && <Devices devices={data.devices} total={data.devicesTotal} offset={loadedOffsets.devices} onPage={(value) => { setOffset(value); setSelected([]); }} selected={selected} onSelect={setSelected} onAdd={() => setAdding(true)} onLaunch={() => setLaunching({ ids: [...selected] })} canAdd={can("devices.write")} canLaunch={can("runs.execute")} />}
          {view === "workflows" && <Workflows workflows={data.workflows} onLaunch={(workflow) => setLaunching({ workflow, ids: [] })} onSchedule={setScheduling} canBuild={can("workflows.write")} canLaunch={can("runs.execute")} onChanged={() => void load()} />}
          {view === "schedules" && <Schedules devices={data.devices} workflows={data.workflows} canWrite={can("schedules.write")} onInitialUsed={() => {}} onOpenRun={setRunId} />}
          {view === "activity" && <Activity runs={data.runs} total={data.summary.runs_total} offset={loadedOffsets.runs} onPage={setRunOffset} onOpen={setRunId} onLaunch={() => setLaunching({ ids: [] })} canLaunch={can("runs.execute")} />}
        </>}
      </main>
    </div>
    {adding && can("devices.write") && <DeviceForm hosts={[...new Set(data?.devices.map(d => d.host_id) ?? [])]} onClose={() => setAdding(false)} onAdded={() => { setAdding(false); setNotice(t("Téléphone ajouté. Sa connexion reste à vérifier sur le worker.")); void load(); }} />}
    {launching && data && can("runs.execute") && <RunDialog userId={user.id} devices={data.devices} workflows={data.workflows} initialWorkflow={launching.workflow} initialDeviceIds={launching.ids} onClose={() => setLaunching(null)} onLaunched={launched} />}
    {scheduling && data && can("schedules.write") && <ScheduleEditor devices={data.devices} workflows={data.workflows} initial={scheduling} onClose={() => setScheduling(null)} onSaved={() => {setScheduling(null); setNotice(t("Planification créée."));}} />}
    {runId && <RunDetail canCancel={can("runs.cancel")} key={runId} runId={runId} onClose={() => setRunId(null)} onChanged={() => void load()} />}
  </div>;
}
