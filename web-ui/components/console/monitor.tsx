"use client";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useLocale, useT } from "../../lib/i18n";
import { currentSignals, signalIsFresh, streamIsFresh, type MonitorSnapshot, type MonitorWindow } from "../../lib/monitoring";
import { ErrorNotice } from "./shared";
import { Icon } from "./icons";

const labels = { api: "API de contrôle", "api-go": "API Go", scheduler: "Ordonnanceur", worker: "Worker Android" };
const periods = [{ value: "1h", label: "1 heure" }, { value: "24h", label: "24 heures" }, { value: "7d", label: "7 jours" }] as const;
const outcomes = [
  { key: "succeeded", label: "Réussies", color: "success" }, { key: "failed", label: "Échouées", color: "failure" },
  { key: "cancelled", label: "Annulées", color: "cancelled" }, { key: "needs_review", label: "À vérifier", color: "review" }
] as const;

export function Monitor() {
  const t = useT(), { locale } = useLocale();
  const [data, setData] = useState<MonitorSnapshot | null>(null), [period, setPeriod] = useState<MonitorWindow>("24h");
  const [transport, setTransport] = useState<"connecting" | "live" | "lost" | "paused">("connecting");
  const [now, setNow] = useState(0), [error, setError] = useState(""), [archives, setArchives] = useState(false);
  const received = useRef<number | null>(null);
  useEffect(() => {
    let source: EventSource | null = null;
    received.current = null; setData(null); setError("");
    function connect() {
      source?.close(); source = null;
      if (document.visibilityState === "hidden") { setTransport("paused"); return; }
      setTransport("connecting");
      const stream = new EventSource(`/api/control/console/monitor/stream?window=${period}`); source = stream;
      stream.onmessage = (event) => {
        if (source !== stream) return;
        try {
          const snapshot = JSON.parse(event.data) as MonitorSnapshot;
          if (!snapshot.queue || !snapshot.capacity || !snapshot.fleet || !snapshot.freshness || !snapshot.schedule_health || !snapshot.database || !snapshot.web || !snapshot.results || snapshot.results.window !== period || !Array.isArray(snapshot.services) || !Array.isArray(snapshot.hosts) || !Number.isFinite(Date.parse(snapshot.observed_at))) throw new Error();
          received.current = performance.now(); setNow(received.current); setData(snapshot); setTransport("live"); setError("");
        } catch { setTransport("lost"); setError("Les mesures sont indisponibles. Les dernières données sont conservées."); }
      };
      stream.onerror = () => { if (source === stream) { setTransport("lost"); setError("Le flux de monitoring est interrompu. Reconnexion automatique…"); } };
      stream.addEventListener("unavailable", () => { if (source === stream) { setTransport("lost"); setError("Les mesures sont indisponibles. Les dernières données sont conservées."); } });
      stream.addEventListener("revoked", () => { if (source === stream) { stream.close(); window.location.assign("/connexion"); } });
    }
    connect(); const timer = setInterval(() => setNow(performance.now()), 1000);
    document.addEventListener("visibilitychange", connect);
    return () => { source?.close(); source = null; clearInterval(timer); document.removeEventListener("visibilitychange", connect); };
  }, [period]);
  const live = transport === "live" && streamIsFresh(received.current, now);
  const elapsed = received.current === null ? 0 : Math.max(0, (now - received.current) / 1000);
  const number = (value: number | null | undefined, digits = 0) => typeof value === "number" && Number.isFinite(value) ? new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(value) : "—";
  const duration = (value: number | null | undefined) => {
    if (value == null || !Number.isFinite(value)) return "—";
    const unit = value >= 3600 ? "hour" : value >= 60 ? "minute" : "second";
    return new Intl.NumberFormat(locale, { style: "unit", unit, unitDisplay: "short", maximumFractionDigits: 1 }).format(value / (unit === "hour" ? 3600 : unit === "minute" ? 60 : 1));
  };
  const bytes = (value: number | null | undefined) => value == null ? "—" : t("{n} Mio", { n: number(value / 1048576, 1) });
  const timestamp = (value: string | null | undefined) => value ? new Intl.DateTimeFormat(locale, { dateStyle: "short", timeStyle: "medium", calendar: "gregory" }).format(new Date(value)) : t("Non renseigné");
  const ratio = (used: number | null | undefined, total: number | null | undefined) => <bdi dir="ltr">{number(used)} / {number(total)}</bdi>;
  const signals = data ? archives ? data.services : currentSignals(data.services) : [];
  const historicalCount = data ? data.services.length - currentSignals(data.services).length : 0;
  const healthy = (component: string) => !!data && live && data.services.some(service => service.component === component && signalIsFresh(service, elapsed, data.freshness.stale_after_seconds));
  const node = (label: string, ready: boolean, detail: string) => <div className={`architecture-node ${ready ? "architecture-node--ready" : "architecture-node--inactive"}`}><span className="status-dot" /><strong>{t(label)}</strong><span>{t(!live ? "État non confirmé" : ready ? "Signal confirmé" : "À vérifier")}</span><small>{detail}</small></div>;
  const connectionLabel = transport === "paused" ? "En pause" : live ? "En direct" : transport === "connecting" ? "Connexion…" : "Mesures périmées";
  const stale = transport === "live" && !live && received.current !== null;
  return <div className="monitor-layout">
    <div className="monitor-heading"><div><h2>{t("Santé de la solution")}</h2><p>{t("Capacité actuelle et résultats mesurés, avec leur période et leur fraîcheur.")}</p></div><span className={`status-badge status-badge--${live ? "green" : "amber"}`} role="status"><span className="status-dot" />{t(connectionLabel)}</span></div>
    {(error || stale) && <ErrorNotice message={t(error || "Aucune nouvelle mesure depuis plus de 10 secondes. Les valeurs affichées sont anciennes.")} />}
    <div className="monitor-toolbar"><fieldset className="monitor-period"><legend>{t("Période des résultats")}</legend>{periods.map(item => <button key={item.value} type="button" aria-pressed={period === item.value} onClick={() => setPeriod(item.value)}>{t(item.label)}</button>)}</fieldset><span className="small-copy">{t("Dernière mesure")} : {data ? timestamp(data.observed_at) : "—"}</span></div>
    {!data ? <section className="surface loading-state" role="status">{t("Connexion aux mesures en direct…")}</section> : <>
      <div className={`monitor-summary ${!live ? "monitor-values--stale" : ""}`}>
        <Metric label={t("Exécutions en attente")} value={number(data.queue.queued)} icon="clock" detail={data.queue.queued ? t("Plus ancienne attente : {duration}", { duration: duration(data.queue.oldest_age_seconds === null ? null : data.queue.oldest_age_seconds + elapsed) }) : t("Aucune exécution en attente")} />
        <Metric label={t("Appareils prêts")} value={ratio(data.fleet.ready, data.fleet.total)} icon="phone" detail={t("{n} connectés · {busy} réservés", { n: number(data.fleet.connected), busy: number(data.fleet.busy) })} />
        <Metric label={t("Workers occupés")} value={ratio(data.capacity.busy_workers, data.capacity.live_workers)} icon="activity" detail={data.capacity.live_workers ? t("{n} emplacements libres", { n: number(data.capacity.idle_workers) }) : t("Aucune capacité confirmée")} />
        <Metric label={t("Taux de réussite")} value={data.results.success_percent === null ? "—" : new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 }).format(data.results.success_percent / 100)} icon="check" detail={t("{n} réussites sur {total} résultats évalués", { n: number(data.results.succeeded), total: number(data.results.succeeded + data.results.failed) })} />
      </div>
      {(data.capacity.unconfirmed_leases > 0 || data.fleet.needs_review > 0 || data.schedule_health.overdue > 0 || data.schedule_health.errors > 0 || (data.queue.queued > 0 && !data.capacity.live_workers)) && <section className="surface monitor-attention"><h2><Icon name="warning" />{t("Points à vérifier")}</h2><ul>
        {data.queue.queued > 0 && !data.capacity.live_workers && <li>{t("La file attend un worker actif.")} <a href="/activite">{t("Voir les exécutions")}</a></li>}
        {data.capacity.unconfirmed_leases > 0 && <li>{t("{n} réservations ont un worker sans signal récent.", { n: number(data.capacity.unconfirmed_leases) })}</li>}
        {data.fleet.needs_review > 0 && <li>{t("{n} appareils nécessitent une vérification.", { n: number(data.fleet.needs_review) })} <a href="/telephones">{t("Appareils")}</a></li>}
        {data.schedule_health.overdue > 0 && <li>{t("{n} planifications ont plus de 30 secondes de retard.", { n: number(data.schedule_health.overdue) })} <a href="/planifications">{t("Planifications")}</a></li>}
        {data.schedule_health.errors > 0 && <li>{t("{n} planifications signalent une erreur.", { n: number(data.schedule_health.errors) })} <a href="/planifications">{t("Planifications")}</a></li>}
      </ul>{!live && <p className="small-copy">{t("Ces constats proviennent de la dernière mesure reçue.")}</p>}</section>}
      <section className="surface monitor-results">
        <div className="surface-heading"><div><h2>{t("Résultats des exécutions")}</h2><p>{t("{n} exécutions terminées sur la période sélectionnée", { n: number(data.results.sample_size) })}</p></div><a className="text-button" href="/activite">{t("Voir les exécutions")}<Icon name="arrow" size={16} /></a></div>
        {data.results.truncated && <p className="notice notice--warning">{t("Volume élevé : seuls les {n} résultats les plus récents de cette période sont analysés.", { n: number(data.results.sample_limit) })}</p>}
        {data.results.sample_size ? <><div className="monitor-outcome-bar" aria-hidden="true">{outcomes.map(item => <span key={item.key} className={`monitor-outcome--${item.color}`} style={{ flexGrow: data.results[item.key] }} />)}</div><ul className="monitor-outcomes">{outcomes.map(item => <li key={item.key}><span className={`monitor-outcome-dot monitor-outcome--${item.color}`} /><span>{t(item.label)}</span><strong>{number(data.results[item.key])}</strong></li>)}</ul></> : <p className="monitor-empty">{t("Aucune exécution terminée sur cette période. Les taux et les durées restent inconnus.")}</p>}
        <dl className="monitor-facts"><Fact label={t("Durée médiane")} value={duration(data.results.duration_p50_seconds)} /><Fact label={t("Durée p95")} value={duration(data.results.duration_p95_seconds)} /><Fact label={t("Attente avant démarrage p95")} value={duration(data.results.queue_wait_p95_seconds)} /><Fact label={t("Dernière réussite, toutes périodes")} value={timestamp(data.results.last_success_at)} /></dl>
        <p className="monitor-note">{t("La réussite compare les succès aux succès + échecs. Annulations et vérifications sont comptées séparément.")}</p><p className="monitor-note">{t("Le p95 couvre 95 % des durées observées. Durée : {duration} mesures · attente : {wait} mesures.", { duration: number(data.results.duration_sample_size), wait: number(data.results.queue_wait_sample_size) })}</p>
      </section>
      <section className="surface architecture-board" aria-label={t("État de l’architecture")}>
        <div className="monitor-section-heading"><h2>{t("Architecture en direct")}</h2><p>{t("Un signal de vie confirme le processus, pas la réussite d’un parcours.")}</p></div>
        <div className="monitor-entry-nodes">{node("Interface web", live && data.web.status === "ready", data.web.status === "unconfigured" ? t("Sonde non configurée") : t("Console de pilotage mobile"))}{node("API de contrôle", healthy("api"), t("Sessions, droits et commandes"))}</div>
        <div className="architecture-branches">{node("PostgreSQL", live && data.database.status === "ready", t("{n} ms · connexion et requête témoin", { n: number(data.database.latency_ms, 1) }))}{node("Ordonnanceur", healthy("scheduler"), t("{n} planifications actives", { n: number(data.schedules.enabled) }))}{node("Workers Android", healthy("worker"), t("{n} workers actifs", { n: number(data.capacity.live_workers) }))}</div>
        <dl className="monitor-facts monitor-database-facts"><Fact label={t("Connexions PostgreSQL (cluster)")} value={ratio(data.database.connections_used, data.database.connections_max)} /><Fact label={t("Taille de la base")} value={bytes(data.database.size_bytes)} /><Fact label={t("Exécutions actives")} value={number(data.queue.active)} /><Fact label={t("En attente d’authentification")} value={number(data.queue.waiting_auth)} /></dl>
        <p className="architecture-footnote">{t("Chaque worker dispose d’un emplacement d’exécution. Le nombre d’appareils connectés reste une mesure distincte.")}</p>
      </section>
      <section className="surface">
        <div className="surface-heading"><div><h2>{t("Services et ressources")}</h2><p>{t("CPU et mémoire du processus uniquement, hors commandes ADB enfants et émulateur Android.")}</p></div></div>
        {historicalCount > 0 && <label className="monitor-archives"><input type="checkbox" checked={archives} onChange={event => setArchives(event.target.checked)} />{t("Afficher les anciennes instances ({n})", { n: number(historicalCount) })}</label>}
        <div className="table-scroll" role="region" aria-label={t("Mesures des services")} tabIndex={0}><table className="data-table monitor-services"><thead><tr><th>{t("Service")}</th><th>{t("Instance / hôte")}</th><th>{t("Dernier signal")}</th><th>{t("CPU consommé")}</th><th>{t("Mémoire RSS")}</th><th>{t("Temps d’activité")}</th><th>{t("Exécutions actives")}</th></tr></thead><tbody>{signals.map(service => {
          const confirmed = live && signalIsFresh(service, elapsed, data.freshness.stale_after_seconds), resources = service.metrics?.resources;
          return <tr key={`${service.component}:${service.instance_id}`} className={!confirmed ? "monitor-row--stale" : undefined}>
            <td><strong>{t(labels[service.component as keyof typeof labels] ?? service.component)}</strong><span className={`status-badge status-badge--${confirmed ? "green" : "amber"}`}>{t(!live ? "État non confirmé" : confirmed ? "Signal récent" : service.status === "missing" ? "Non démarré" : "Signal périmé")}</span></td>
            <td><code dir="ltr">{service.host_id || service.instance_id}</code>{service.host_id && <small><code dir="ltr">{service.instance_id}</code></small>}</td>
            <td>{service.age_seconds === null ? "—" : duration(service.age_seconds + elapsed)}<small>{timestamp(service.last_seen_at)}</small></td>
            <td>{confirmed && resources?.scope === "process" && resources.cpu_cores !== null ? t("{n} cœur(s)", { n: number(resources.cpu_cores, 3) }) : "—"}</td>
            <td>{confirmed && resources?.scope === "process" ? bytes(resources.memory_rss_bytes) : "—"}</td><td>{confirmed && resources ? duration(resources.uptime_seconds + elapsed) : "—"}</td><td>{confirmed ? number(service.active_executions) : "—"}</td>
          </tr>;
        })}</tbody></table></div><p className="monitor-note">{t("1 cœur consommé correspond à un cœur CPU entièrement utilisé pendant l’intervalle de mesure. Une mesure absente n’est pas un zéro.")}</p>
      </section>
      <section className="surface">
        <div className="surface-heading"><div><h2>{t("Hôtes et capacité des appareils")}</h2><p>{t("La connexion provient d’une observation ADB récente. Un appareil déclaré seul n’est pas considéré prêt.")}</p></div></div>
        <div className="table-scroll" role="region" aria-label={t("Capacité par hôte")} tabIndex={0}><table className="data-table"><thead><tr><th>{t("Hôte")}</th><th>{t("Workers occupés / actifs")}</th><th>{t("Connectés / déclarés")}</th><th>{t("Appareils prêts")}</th><th>{t("Exécutions en attente")}</th></tr></thead><tbody>{data.hosts.map(host => <tr key={host.host_id}><td><code dir="ltr">{host.host_id}</code></td><td>{ratio(host.busy_workers, host.live_workers)}</td><td>{ratio(host.connected_devices, host.devices)}</td><td>{number(host.ready_devices)}</td><td>{number(host.queued)}</td></tr>)}</tbody></table></div>
        {!data.hosts.length && <p className="monitor-empty">{t("Aucun appareil enregistré.")}</p>}
        <div className="monitor-fleet-status"><span>{t("{n} appareils sans worker récent", { n: number(data.fleet.worker_offline) })}</span><span>{t("{n} appareils hors ligne", { n: number(data.fleet.offline + data.fleet.not_connected) })}</span><span>{t("{n} autorisations Android requises", { n: number(data.fleet.unauthorized) })}</span><span>{t("{n} connexions non confirmées", { n: number(data.fleet.unknown) })}</span></div>
      </section>
    </>}
  </div>;
}

function Metric({ label, value, detail, icon }: { label: string; value: ReactNode; detail: string; icon: "clock" | "phone" | "activity" | "check" }) {
  return <section className="surface monitor-metric"><span><Icon name={icon} size={18} />{label}</span><strong>{value}</strong><small>{detail}</small></section>;
}
function Fact({ label, value }: { label: string; value: ReactNode }) { return <div><dt>{label}</dt><dd>{value}</dd></div>; }
