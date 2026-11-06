"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { buildArchitecture, hasRecentActivity, type ArchitectureEvent, type ArchitectureNodeId, type ArchitectureState } from "../../lib/architecture";
import { currentSignals, signalIsFresh, type MonitorSnapshot } from "../../lib/monitoring";
import { useLocale, useT } from "../../lib/i18n";
import { Dialog } from "./shared";
import { Icon } from "./icons";

const stateLabels = { active: "Activité observée", ready: "Signal confirmé", warning: "À vérifier", unknown: "État non confirmé" };
const nodeIcons = { web: "overview", api: "shield", "api-go": "activity", database: "archive", scheduler: "clock", workers: "workflow", android: "phone", artifacts: "archive" } as const;
const descriptions: Record<ArchitectureNodeId, string> = {
  web: "La console reçoit vos commandes et affiche les mesures de la solution.",
  api: "L’API Python gère les sessions, les droits et les commandes.",
  "api-go": "L’API Go assure les lectures du tableau de bord et de la flotte.",
  database: "PostgreSQL conserve la file des exécutions, les réservations et les résultats.",
  scheduler: "L’ordonnanceur crée les exécutions prévues par vos planifications.",
  workers: "Les workers prennent les exécutions dans la file et pilotent les appareils.",
  android: "La connexion des appareils est vérifiée par une observation ADB récente.",
  artifacts: "Les captures des étapes sont conservées et consultables avec les droits de l’exécution."
};
const activityLabels: Record<ArchitectureEvent, string> = {
  console_commands: "Commandes enregistrées", scheduled_runs: "Lancements planifiés", executions_started: "Exécutions démarrées",
  actions_completed: "Actions terminées", steps_published: "Étapes publiées", captures_published: "Captures publiées"
};
const nodeEvents: Partial<Record<ArchitectureNodeId, ArchitectureEvent[]>> = {
  web: ["console_commands"], api: ["console_commands"], database: ["scheduled_runs", "executions_started"],
  scheduler: ["scheduled_runs"], workers: ["executions_started", "actions_completed", "steps_published"],
  android: ["actions_completed"], artifacts: ["captures_published"]
};
type Drawing = { width: number; height: number; paths: { id: string; d: string }[] };

export function ArchitectureMap({ data, live, elapsed, permissions = [] }: { data: MonitorSnapshot; live: boolean; elapsed: number; permissions?: string[] }) {
  const t = useT(), { locale } = useLocale(), markerId = useId().replace(/:/g, "");
  const [selected, setSelected] = useState<ArchitectureNodeId | null>(null), [paused, setPaused] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(true), [visible, setVisible] = useState(true);
  const [drawing, setDrawing] = useState<Drawing>({ width: 0, height: 0, paths: [] });
  const board = useRef<HTMLDivElement>(null);
  const model = buildArchitecture(data, live, elapsed), selectedNode = model.nodes.find(node => node.id === selected);
  const number = (value: number | null | undefined, digits = 0) => typeof value === "number" && Number.isFinite(value) ? new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(value) : "—";
  const timestamp = (value: string | null | undefined) => value && Number.isFinite(Date.parse(value)) ? new Intl.DateTimeFormat(locale, { dateStyle: "short", timeStyle: "medium", calendar: "gregory" }).format(new Date(value)) : t("Non renseigné");
  const bytes = (value: number | null | undefined) => value == null ? "—" : t("{n} Mio", { n: number(value / 1048576, 1) });
  const ratio = (value: number | null | undefined, total: number | null | undefined) => <bdi dir="ltr">{number(value)} / {number(total)}</bdi>;
  const observationElapsed = elapsed + (data.topology?.sample_age_seconds ?? 0);
  const moving = live && visible && !paused && !reducedMotion;

  useEffect(() => {
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(preference.matches), visibility = () => setVisible(document.visibilityState !== "hidden");
    update(); visibility(); preference.addEventListener("change", update); document.addEventListener("visibilitychange", visibility);
    return () => { preference.removeEventListener("change", update); document.removeEventListener("visibilitychange", visibility); };
  }, []);

  useEffect(() => {
    const element = board.current;
    if (!element) return;
    let frame = 0;
    function measure() {
      if (!element) return;
      const bounds = element.getBoundingClientRect(), compact = bounds.width < 680;
      const rects = new Map(Array.from(element.querySelectorAll<HTMLButtonElement>("[data-node-id]")).map(button => {
        const rect = button.getBoundingClientRect();
        return [button.dataset.nodeId, { x: rect.left - bounds.left, y: rect.top - bounds.top, w: rect.width, h: rect.height }];
      }));
      const paths = model.edges.flatMap((edge, index) => {
        const from = rects.get(edge.from), to = rects.get(edge.to);
        if (!from || !to) return [];
        let d: string;
        if (compact) {
          const left = index % 2 === 0, lane = 6 + Math.floor(index / 2) * 3;
          const rail = left ? lane : bounds.width - lane;
          const startX = from.x + (left ? 0 : from.w), endX = to.x + (left ? 0 : to.w);
          const startY = from.y + from.h / 2 + (index % 3 - 1) * 12, endY = to.y + to.h / 2 + (index % 3 - 1) * 12;
          d = `M ${startX} ${startY} H ${rail} V ${endY} H ${endX}`;
        } else if (edge.id === "web-api-go") {
          const startX = from.x + from.w / 2, endX = to.x + to.w / 2;
          d = `M ${startX} ${from.y} V 10 H ${endX} V ${to.y}`;
        } else if (Math.abs(from.y - to.y) < 20) {
          const right = to.x > from.x, offset = edge.id === "api-web" ? 14 : -14;
          const startX = from.x + (right ? from.w : 0), endX = to.x + (right ? 0 : to.w);
          const startY = from.y + from.h / 2 + offset, endY = to.y + to.h / 2 + offset;
          d = `M ${startX} ${startY} C ${(startX + endX) / 2} ${startY}, ${(startX + endX) / 2} ${endY}, ${endX} ${endY}`;
        } else if (Math.abs(from.x - to.x) < 20) {
          const down = to.y > from.y, x = from.x + from.w / 2 + (index % 3 - 1) * 14;
          d = `M ${x} ${from.y + (down ? from.h : 0)} V ${to.y + (down ? 0 : to.h)}`;
        } else if (edge.id === "workers-artifacts") {
          const right = to.x > from.x, startX = from.x + (right ? from.w : 0);
          const rail = (startX + to.x + (right ? 0 : to.w)) / 2, startY = from.y + from.h / 2;
          const endX = to.x + to.w / 2, endY = to.y + to.h, middleY = (from.y + endY) / 2;
          d = `M ${startX} ${startY} H ${rail} V ${middleY} H ${endX} V ${endY}`;
        } else {
          const offset = (index % 4 - 1.5) * 8;
          const down = to.y > from.y, startX = from.x + from.w / 2 + offset, endX = to.x + to.w / 2 + offset;
          const startY = from.y + (down ? from.h : 0), endY = to.y + (down ? 0 : to.h), middleY = (startY + endY) / 2 + offset;
          d = `M ${startX} ${startY} V ${middleY} H ${endX} V ${endY}`;
        }
        return [{ id: edge.id, d }];
      });
      setDrawing({ width: bounds.width, height: bounds.height, paths });
    }
    function schedule() { cancelAnimationFrame(frame); frame = requestAnimationFrame(measure); }
    const observer = new ResizeObserver(schedule); observer.observe(element);
    element.querySelectorAll("[data-node-id]").forEach(button => observer.observe(button));
    schedule();
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
    // Geometry depends on translated text, not on the two-second measurements.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale]);

  function subtitle(id: ArchitectureNodeId) {
    switch (id) {
      case "web": return t("Console et accès sécurisés");
      case "api": return "Python";
      case "api-go": return "Go";
      case "database": return t("File persistée et réservations");
      case "scheduler": return t("{n} planifications actives", { n: number(data.schedules.enabled) });
      case "workers": return t("{busy} occupés · {n} actifs", { busy: number(data.capacity.busy_workers), n: number(data.capacity.live_workers) });
      case "android": return t("{connected} connectés · {ready} prêts", { connected: number(data.fleet.connected), ready: number(data.fleet.ready) });
      case "artifacts": return t("Captures privées des étapes");
    }
  }
  function facts(id: ArchitectureNodeId) {
    switch (id) {
      case "web": return <><Fact label={t("Sonde web")} value={t(data.web.status === "ready" ? "Signal confirmé" : data.web.status === "unconfigured" ? "Sonde non configurée" : "À vérifier")} /><Fact label={t("Mesures en direct")} value={t(live ? "En direct" : "Mesures périmées")} /></>;
      case "api": case "api-go": return null;
      case "database": return <><Fact label={t("Latence PostgreSQL")} value={t("{n} ms", { n: number(data.database.latency_ms, 1) })} /><Fact label={t("Connexions PostgreSQL (cluster)")} value={ratio(data.database.connections_used, data.database.connections_max)} /><Fact label={t("Taille de la base")} value={bytes(data.database.size_bytes)} /><Fact label={t("Exécutions en attente")} value={number(data.queue.queued)} /><Fact label={t("Exécutions actives")} value={number(data.queue.active)} /><Fact label={t("En attente d’authentification")} value={number(data.queue.waiting_auth)} /></>;
      case "scheduler": return <><Fact label={t("Planifications actives")} value={number(data.schedules.enabled)} /><Fact label={t("Prochain lancement")} value={timestamp(data.schedules.next_run_at)} /><Fact label={t("Planifications en retard")} value={number(data.schedule_health.overdue)} /><Fact label={t("Planifications en erreur")} value={number(data.schedule_health.errors)} /></>;
      case "workers": return <><Fact label={t("Workers occupés / actifs")} value={ratio(data.capacity.busy_workers, data.capacity.live_workers)} /><Fact label={t("Workers libres")} value={number(data.capacity.idle_workers)} /><Fact label={t("Réservations non confirmées")} value={number(data.capacity.unconfirmed_leases)} /><Fact label={t("Exécutions confirmées à la mesure")} value={number(data.topology?.confirmed_device_executions)} /></>;
      case "android": return <><Fact label={t("Connectés / déclarés")} value={ratio(data.fleet.connected, data.fleet.total)} /><Fact label={t("Appareils prêts")} value={number(data.fleet.ready)} /><Fact label={t("Appareils réservés")} value={number(data.fleet.busy)} /><Fact label={t("Appareils à vérifier")} value={number(data.fleet.needs_review)} /></>;
      case "artifacts": return <Fact label={t("Lecture du stockage")} value={t(data.topology?.storage.status === "readable" ? "Lecture confirmée" : data.topology?.storage.status === "unavailable" ? "Lecture indisponible" : "Non mesuré")} />;
    }
  }
  const selectedServices = selected === "api" || selected === "api-go" || selected === "scheduler" || selected === "workers"
    ? currentSignals(data.services.filter(service => service.component === (selected === "workers" ? "worker" : selected))) : [];
  const detailLinks = selected === "android" ? [{ href: "/telephones", permission: "devices.read", label: "Appareils" }]
    : selected === "scheduler" ? [{ href: "/planifications", permission: "schedules.read", label: "Planifications" }]
      : selected === "database" || selected === "workers" || selected === "artifacts" ? [{ href: "/activite", permission: "runs.read", label: "Voir les exécutions" }] : [];

  return <section className="surface architecture-map" aria-labelledby={`${markerId}-heading`}>
    <div className="architecture-map-heading"><div><h2 id={`${markerId}-heading`}>{t("Architecture en direct")}</h2><p>{t("Sélectionnez un composant pour voir ses mesures et son rôle.")}</p></div><button type="button" className="text-button architecture-motion-toggle" aria-pressed={paused} disabled={reducedMotion} onClick={() => setPaused(value => !value)}>{t(paused ? "Reprendre les animations" : "Mettre les animations en pause")}</button></div>
    <p className="architecture-map-freshness">{t("Dernière mesure")} : {timestamp(data.observed_at)}{!live && <strong>{t("Mesures périmées")}</strong>}{reducedMotion && <span>{t("Animations réduites selon vos préférences.")}</span>}</p>
    <div className="architecture-map-canvas" ref={board} data-motion={moving ? "running" : "paused"}>
      {drawing.width > 0 && <svg className="architecture-map-connectors" viewBox={`0 0 ${drawing.width} ${drawing.height}`} width={drawing.width} height={drawing.height} aria-hidden="true" focusable="false"><defs>{(["active", "ready", "warning", "unknown"] as ArchitectureState[]).map(state => <marker key={state} id={`${markerId}-${state}`} markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto" markerUnits="userSpaceOnUse"><path d="M 1 1 L 6 3.5 L 1 6" fill="none" className={`architecture-arrow architecture-arrow--${state}`} /></marker>)}</defs>{model.edges.map(edge => { const path = drawing.paths.find(item => item.id === edge.id); return path && <g key={edge.id} data-edge-id={edge.id} data-state={edge.state} className={`architecture-edge architecture-edge--${edge.state}`}><path d={path.d} fill="none" markerEnd={`url(#${markerId}-${edge.state})`} /></g>; })}</svg>}
      {model.nodes.map(node => <button key={node.id} type="button" data-node-id={node.id} data-state={node.state} className={`architecture-map-node architecture-map-node--${node.id}`} aria-haspopup="dialog" onClick={() => setSelected(node.id)}><span className="architecture-map-node-icon"><Icon name={nodeIcons[node.id]} size={21} /></span><span className="architecture-map-node-name">{t(node.label)}</span><span className="architecture-map-node-summary">{subtitle(node.id)}</span><State state={node.state} /><span className="architecture-map-node-open" aria-hidden="true"><Icon name="arrow" size={16} /></span></button>)}
    </div>
    <div className="architecture-map-legend"><span><i className="architecture-legend-line architecture-legend-line--active" aria-hidden="true" />{t("Activité observée")}</span><span><i className="architecture-legend-line" aria-hidden="true" />{t("Liaison disponible")}</span><span><i className="architecture-legend-line architecture-legend-line--unknown" aria-hidden="true" />{t("État non confirmé")}</span></div>
    <p className="architecture-map-note">{t("Les mouvements indiquent un événement récent, une exécution confirmée ou le flux de mesures reçu ; ils ne représentent pas un débit réseau.")}</p>
    {model.sampled && <p className="notice notice--warning architecture-map-sampling">{t("Volume élevé : les compteurs d’activité récente peuvent être incomplets.")}</p>}
    <details className="architecture-map-connections"><summary>{t("Comprendre les liaisons")}</summary><ul>{model.edges.map(edge => <li key={edge.id}><div><strong>{t(model.nodes.find(node => node.id === edge.from)!.label)} <bdi aria-hidden="true">→</bdi> {t(model.nodes.find(node => node.id === edge.to)!.label)}</strong><State state={edge.state} /></div><span>{t(edge.label)}</span><small>{t(edge.evidence === "stream" ? "Flux de mesures reçu" : edge.evidence === "execution" ? "Réservation et connexion de l’appareil confirmées" : edge.evidence === "recent" ? "Activité observée sur les {seconds} dernières secondes" : "Liaison d’architecture ; débit non mesuré", { seconds: number(model.windowSeconds) })}</small></li>)}</ul></details>
    {selectedNode && <Dialog title={t(selectedNode.label)} description={t(descriptions[selectedNode.id])} onClose={() => setSelected(null)} wide className="architecture-detail-dialog"><div className="architecture-detail-body"><div className="architecture-detail-status"><State state={selectedNode.state} /><span>{t("Dernière mesure")} : {timestamp(data.observed_at)}</span></div>{!live && <p className="notice notice--warning">{t("Ces constats proviennent de la dernière mesure reçue.")}</p>}
      <dl className="architecture-detail-facts">{facts(selectedNode.id)}</dl>
      {selectedNode.id === "web" || selectedNode.id === "api" || selectedNode.id === "api-go" ? <p className="architecture-map-note">{t("L’activité HTTP détaillée n’est pas mesurée.")}</p> : null}
      {selectedNode.id === "workers" && <p className="architecture-map-note">{t("Chaque worker dispose d’un emplacement d’exécution. Le nombre d’appareils connectés reste une mesure distincte.")}</p>}
      {selectedNode.id === "artifacts" && <p className="architecture-map-note">{t("La sonde vérifie la lecture du dossier ; elle ne teste pas l’écriture ni l’espace disque.")}</p>}
      {selectedServices.length > 0 && <section className="architecture-detail-section"><h3>{t("Instances du service")}</h3><p>{t("CPU et mémoire du processus uniquement, hors commandes ADB enfants et émulateur Android.")}</p><ul className="architecture-instance-list">{selectedServices.map(service => {
        const fresh = live && signalIsFresh(service, observationElapsed, data.freshness.stale_after_seconds), resources = service.metrics?.resources;
        return <li key={`${service.component}:${service.instance_id}`}><div><code dir="ltr">{service.host_id || service.instance_id}</code><State state={fresh ? "ready" : "unknown"} /></div>{service.host_id && <small><code dir="ltr">{service.instance_id}</code></small>}<dl className="architecture-detail-facts"><Fact label={t("Dernier signal")} value={timestamp(service.last_seen_at)} /><Fact label={t("CPU consommé")} value={fresh && resources?.scope === "process" && resources.cpu_cores !== null ? t("{n} cœur(s)", { n: number(resources.cpu_cores, 3) }) : "—"} /><Fact label={t("Mémoire RSS")} value={fresh && resources?.scope === "process" ? bytes(resources.memory_rss_bytes) : "—"} /><Fact label={t("Exécutions actives")} value={fresh ? number(service.active_executions) : "—"} /></dl></li>;
      })}</ul></section>}
      {nodeEvents[selectedNode.id] && <section className="architecture-detail-section"><h3>{t("Activité observée sur les {seconds} dernières secondes", { seconds: number(model.windowSeconds) })}</h3><p>{t("Fenêtre terminée à la dernière mesure. Un compteur absent reste inconnu.")}</p>{model.sampled && <p className="notice notice--warning">{t("Volume élevé : les compteurs d’activité récente peuvent être incomplets.")}</p>}<ul className="architecture-activity-list">{nodeEvents[selectedNode.id]!.map(key => { const event = data.topology?.events[key]; return <li key={key}><div><span>{t(activityLabels[key])}</span><strong>{number(event?.count)}</strong></div><small>{t("Dernier événement")} : {timestamp(event?.last_at)}</small><small>{t(!event ? "Non mesuré" : live && hasRecentActivity(data, key, elapsed) ? "Activité observée" : "Aucune activité récente confirmée")}</small></li>; })}</ul></section>}
      {selectedNode.id === "android" && data.hosts.length > 0 && <section className="architecture-detail-section"><h3>{t("Hôtes et capacité des appareils")}</h3><ul className="architecture-instance-list">{data.hosts.map(host => <li key={host.host_id}><code dir="ltr">{host.host_id}</code><dl className="architecture-detail-facts"><Fact label={t("Connectés / déclarés")} value={ratio(host.connected_devices, host.devices)} /><Fact label={t("Appareils prêts")} value={number(host.ready_devices)} /></dl></li>)}</ul></section>}
      {detailLinks.filter(link => permissions.includes(link.permission)).map(link => <a key={link.href} className="text-button architecture-detail-link" href={link.href}>{t(link.label)}<Icon name="arrow" size={16} /></a>)}
    </div></Dialog>}
  </section>;
}

function State({ state }: { state: ArchitectureState }) {
  const t = useT();
  return <span className={`architecture-state architecture-state--${state}`}><Icon name={state === "warning" ? "warning" : state === "unknown" ? "clock" : state === "active" ? "activity" : "check"} size={13} />{t(stateLabels[state])}</span>;
}
function Fact({ label, value }: { label: string; value: ReactNode }) { return <div><dt>{label}</dt><dd>{value}</dd></div>; }
