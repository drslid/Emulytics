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
import { DeviceForm } from "./device-form";
import { RunDialog } from "./run-dialog";
import { RunDetail } from "./run-detail";
import { useLocale, useT } from "../../lib/i18n";
import { LanguageSelector } from "../language-selector";
import { Schedules, ScheduleEditor } from "./schedules";
import { Monitor } from "./monitor";
import { Logs } from "./logs";
import { Users, Profile } from "./users";
import { connectionWorkerHosts } from "../../lib/device-readiness";
import { ConsoleNavigation } from "./navigation";
import { ManagedEmulators } from "./emulators";
import { currentEmulatorLaunchDevice, mergeEmulatorLaunchDevices } from "../../lib/emulators";
import { Configuration } from "./configuration";
import { FirstRun } from "./first-run";

const titles: Record<View, { title: string; subtitle: string }> = {
  overview: { title: "Tableau de bord", subtitle: "Votre flotte et vos automatisations, au même endroit." },
  devices: { title: "Appareils", subtitle: "Sélectionnez les appareils que vous souhaitez piloter." },
  workflows: { title: "Parcours", subtitle: "Des parcours reproductibles, pour un ou plusieurs téléphones." },
  activity: { title: "Exécutions", subtitle: "Suivez les exécutions et retrouvez leurs résultats." },
  schedules: { title: "Planifications", subtitle: "Choisissez quand lancer un parcours et sur quels appareils." },
  monitor: { title: "Monitoring", subtitle: "Toute l’architecture et son activité en temps réel." },
  logs: { title: "Journal", subtitle: "Les événements et les actions de votre espace." },
  users: { title: "Utilisateurs", subtitle: "Les comptes locaux, leurs rôles et leurs accès." },
  configuration: { title: "Configuration", subtitle: "Vos connexions personnelles et les réglages de la console." },
  profile: { title: "Mon profil", subtitle: "Votre identité, votre rôle et vos préférences." }
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
  const [launching, setLaunching] = useState<{ workflow?: Workflow; ids: string[]; device?: Device } | null>(null);
  const [managedDevices, setManagedDevices] = useState<Device[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const pending = useRef(false);
  const sequence = useRef(0);
  const load = useCallback(async () => {
    const request = ++sequence.current;
    pending.current = true; setRefreshing(true);
    try {
      const [fleet, workflows, runs, summary, emulators] = await Promise.all([
        api<Page<Device> & { worker_hosts?: string[] }>(`console/fleet?limit=100&offset=${offset}`), api<Page<Workflow>>("workflows?limit=100&offset=0"),
        api<Page<Run>>(`runs?limit=100&offset=${runOffset}`), api<Summary>("console/summary"), api<{items: {device_id: string; state: string}[]}>("console/emulators")
      ]);
      if (request !== sequence.current) return;
      const states = new Map(emulators.items.map(emulator => [emulator.device_id, emulator.state]));
      setData({ devices: fleet.items.map(device => states.has(device.device_id) ? {...device, emulator_state: states.get(device.device_id)} : device), devicesTotal: fleet.total ?? fleet.items.length, workerHosts: connectionWorkerHosts(fleet.items, fleet.worker_hosts), workflows: workflows.items, runs: runs.items, summary });
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
  return <div className="app-shell tw:block tw:min-h-dvh tw:min-w-0 tw:min-[901px]:grid tw:min-[901px]:grid-cols-[214px_minmax(0,1fr)] tw:min-[1201px]:grid-cols-[236px_minmax(0,1fr)]">
    <a className="skip-link" href="#main-content">{t("Aller au contenu")}</a>
    <aside className="app-sidebar">
      <a className="app-brand" href="/" aria-label={t("Emulytix, tableau de bord")}><BrandMark /><span>Emulytix<span className="brand-caption">{t("Console opérateur")}</span></span></a>
      <ConsoleNavigation user={user} view={view} needsReviewCount={data?.summary.runs_needs_review ?? 0} />
      <div className="sidebar-bottom"><a href="/profil" className={view === "profile" ? "nav-item nav-item--active" : "nav-item"} aria-current={view === "profile" ? "page" : undefined}><Icon name="users" /><span>{t("Mon profil")}</span></a><div className="sidebar-account"><span className="avatar">{Array.from(user.display_name || user.username)[0]?.toLocaleUpperCase(locale)}</span><div><strong title={user.display_name || user.username}>{user.display_name || user.username}</strong><span>{t({admin:"Admin",builder:"Builder",operator:"Operator",viewer:"Viewer",auditor:"Auditor"}[user.role])}</span></div><button className="icon-button" onClick={() => void logout()} aria-label={t("Se déconnecter")}><Icon name="logout" size={18} /></button></div></div>
    </aside>
    <div className="app-main tw:min-w-0"><header className="topbar"><div><span className="workspace-indicator" />{t("Espace de travail")}<span className="topbar-separator">/</span><strong>{t(title.title)}</strong></div><LanguageSelector /></header>
      <main id="main-content" className="console-content" tabIndex={-1}>
        <div className="page-heading"><div><h1>{t(title.title)}</h1><p>{t(title.subtitle)}</p></div>{dataView && view !== "devices" && view !== "workflows" && view !== "schedules" && can("runs.execute") && <button className="button button--primary" disabled={!data} onClick={() => setLaunching({ ids: [] })}><Icon name="plus" size={19} />{t("Lancer une automatisation")}</button>}</div>
        {dataView && <div className="refresh-line"><span className={`connection-dot ${error ? "connection-dot--offline" : ""}`} /><span>{error ? t("Actualisation interrompue · dernières données conservées") : updatedAt ? t("Mis à jour à {time}", { time: new Intl.DateTimeFormat(locale, { timeStyle: "short" }).format(updatedAt) }) : t("Connexion au service…")}</span><button className="text-button" disabled={refreshing} onClick={() => void load()}><Icon name="refresh" size={15} />{refreshing ? t("Actualisation…") : t("Actualiser")}</button></div>}
        {error && <ErrorNotice message={error} />}
        {notice && <div className="notice notice--success" role="status"><Icon name="check" /><span>{notice}</span><button className="icon-button" onClick={() => setNotice("")} aria-label={t("Masquer la confirmation")}><Icon name="close" size={17} /></button></div>}
        {!allowed ? <section className="surface empty-state"><Icon name="shield" size={32} /><h2>{t("Accès réservé")}</h2><p>{t("Votre rôle ne permet pas d’accéder à cette section.")}</p></section> : view === "configuration" ? <Configuration user={user} /> : view === "profile" ? <Profile user={user} onLogout={() => void logout()} /> : view === "users" ? <Users user={user} /> : view === "monitor" ? <Monitor permissions={user.permissions ?? []} /> : view === "logs" ? <Logs /> : !data ? <section className="surface loading-state" aria-busy={!error} role="status">{error ? <><h2>{t("La console ne peut pas charger vos données")}</h2><p>{t("Vos données restent conservées. Réessayez lorsque le service est disponible.")}</p><button className="button button--secondary" onClick={() => void load()} disabled={refreshing}>{t("Réessayer")}</button></> : <><div className="skeleton-line" /><div className="skeleton-line skeleton-line--short" /><p>{t("Chargement de votre espace…")}</p></>}</section> : <>
          {view === "overview" && <><FirstRun data={data} canBuild={can("workflows.write")} canManage={can("devices.write")} canLaunch={can("runs.execute")} onLaunch={(workflow, ids = []) => setLaunching({workflow, ids})} onOpen={setRunId} onChanged={() => void load()} /><Overview data={data} onOpen={setRunId} onLaunch={() => setLaunching({ ids: [] })} onAdd={() => setAdding(true)} canAdd={can("devices.write")} canLaunch={can("runs.execute")} /></>}
          {view === "devices" && <><ManagedEmulators userId={user.id} devices={data.devices} canManage={can("devices.write")} canLaunch={can("runs.execute")} onChanged={() => void load()} onLaunch={device => setLaunching({ ids: [device.device_id], device })} onOpenRun={setRunId} onDevices={setManagedDevices} /><Devices devices={data.devices} total={data.devicesTotal} offset={loadedOffsets.devices} onPage={(value) => { setOffset(value); setSelected([]); }} selected={selected} onSelect={setSelected} onAdd={() => setAdding(true)} onLaunch={() => setLaunching({ ids: [...selected] })} canAdd={can("devices.write")} canLaunch={can("runs.execute")} /></>}
          {view === "workflows" && <Workflows workflows={data.workflows} onLaunch={(workflow) => setLaunching({ workflow, ids: [] })} onSchedule={setScheduling} canBuild={can("workflows.write")} canLaunch={can("runs.execute")} onChanged={() => void load()} />}
          {view === "schedules" && <Schedules userId={user.id} devices={data.devices} workflows={data.workflows} canWrite={can("schedules.write")} onInitialUsed={() => {}} onOpenRun={setRunId} />}
          {view === "activity" && <Activity runs={data.runs} workflows={data.workflows} total={data.summary.runs_total} offset={loadedOffsets.runs} onPage={setRunOffset} onOpen={setRunId} onLaunch={() => setLaunching({ ids: [] })} canLaunch={can("runs.execute")} />}
        </>}
      </main>
    </div>
    {adding && can("devices.write") && <DeviceForm hosts={data?.workerHosts ?? []} onClose={() => setAdding(false)} onAdded={() => { setAdding(false); setNotice(t("Téléphone ajouté. Sa connexion reste à vérifier sur le worker.")); void load(); }} />}
    {launching && data && can("runs.execute") && <RunDialog userId={user.id} devices={mergeEmulatorLaunchDevices(data.devices, currentEmulatorLaunchDevice(launching.device, managedDevices))} workflows={data.workflows} initialWorkflow={launching.workflow} initialDeviceIds={launching.ids} onClose={() => setLaunching(null)} onLaunched={launched} />}
    {scheduling && data && can("schedules.write") && <ScheduleEditor userId={user.id} devices={data.devices} workflows={data.workflows} initial={scheduling} onClose={() => setScheduling(null)} onSaved={() => {setScheduling(null); setNotice(t("Planification créée."));}} />}
    {runId && <RunDetail canCancel={can("runs.cancel")} canManageDevices={can("devices.write")} key={runId} runId={runId} onClose={() => setRunId(null)} onChanged={() => void load()} />}
  </div>;
}
