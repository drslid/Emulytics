"use client";

import { useLocale } from "../../lib/i18n";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../lib/client-api";
import type { Page, RunDetail as Detail, RunEvent } from "../../lib/console-types";
import { Badge, Dialog, ErrorNotice, date, workflowName } from "./shared";
import { Icon } from "./icons";

const eventLabels: Record<string, string> = {
  "run.created": "Demande enregistrée", "run.cancel_requested": "Arrêt demandé", "run.cancelled": "Exécution annulée",
  "execution.started": "Worker démarré", "execution.finished": "Exécution terminée", "execution.needs_review": "Vérification nécessaire",
  "action.intent": "Action préparée", "action.done": "Action confirmée", "action.failed": "Action échouée",
  "action.cancelled": "Action annulée", "action.uncertain": "Résultat de l’action incertain"
};
export function RunDetail({ runId, onClose, onChanged, canCancel = true }: { runId: string; onClose: () => void; onChanged: () => void; canCancel?: boolean }) {
  const { t, locale } = useLocale();
  const [run, setRun] = useState<Detail | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [eventLoading, setEventLoading] = useState(false);
  const requestSequence = useRef(0);
  const mutating = useRef(false);
  const load = useCallback(async () => {
    if (mutating.current) return;
    const request = ++requestSequence.current;
    try {
      const detail = await api<Detail>(`runs/${runId}`);
      if (request === requestSequence.current && !mutating.current) { setRun(detail); setError(""); }
    } catch (failure) { if (request === requestSequence.current && !mutating.current) setError((failure as Error).message); }
  }, [runId]);
  const moreEvents = useCallback(async (after: number) => {
    setEventLoading(true);
    try {
      const page = await api<Page<RunEvent>>(`runs/${runId}/events?after=${after}&limit=100`);
      setEvents((current) => [...current, ...page.items].filter((item, index, list) => list.findIndex((other) => other.sequence === item.sequence) === index));
    } catch (failure) { setError((failure as Error).message); }
    finally { setEventLoading(false); }
  }, [runId]);
  useEffect(() => {
    void load(); void moreEvents(0);
    const timer = setInterval(() => { if (document.visibilityState === "visible") void load(); }, 5000);
    return () => { clearInterval(timer); requestSequence.current += 1; };
  }, [load, moreEvents]);
  useEffect(() => {
    const timer = setInterval(() => { if (document.visibilityState === "visible") void moreEvents(events.at(-1)?.sequence ?? 0); }, 5000);
    return () => clearInterval(timer);
  }, [events, moreEvents]);
  async function cancel() {
    mutating.current = true; requestSequence.current += 1;
    setBusy(true); setError("");
    try { const result = await api<Detail>(`runs/${runId}/cancel`, {}); requestSequence.current += 1; setRun(result); setConfirmCancel(false); onChanged(); }
    catch (failure) { setError((failure as Error).message); }
    finally { mutating.current = false; setBusy(false); }
  }
  return <Dialog title={run ? t(workflowName(run.workflow_id)) : t("Détail de l’exécution")} description={t("Exécution {id}", { id: runId.slice(0, 8) })} onClose={onClose} wide>
    <div className="dialog-form">
      {error && <ErrorNotice message={error} />}
      {!run ? <p role="status" className="loading-copy">{t("Chargement de l’exécution…")}</p> : <>
        <div className="run-detail-meta"><Badge status={run.status} cancelRequested={run.cancel_requested} /><span>{date(run.created_at, locale)}</span><span>{t("Version")} {run.workflow_version}</span></div>
        {run.status === "queued" && <div className="notice notice--info"><Icon name="clock" /><span>{t("Le worker doit être actif sur chaque hôte. Les téléphones occupés attendront leur tour ; une inscription ne confirme pas une connexion Android.")} <a href="/monitoring">{t("Monitoring")}</a></span></div>}
        {run.cancel_requested && run.status === "running" && <div className="notice notice--warning">{t("Arrêt demandé. Le worker doit encore confirmer sa fin ; l’appareil reste réservé jusque-là.")}</div>}
        {run.status === "needs_review" && <div className="notice notice--warning"><Icon name="warning" /><span>{t("Une vérification est nécessaire avant de réutiliser l’appareil. Consultez les preuves ; aucune action incertaine ne sera relancée automatiquement.")}</span></div>}
        <section><h3 className="detail-section-title">{t("Résultat par téléphone")}</h3><div className="execution-list">{run.executions.map((execution) => <article className="execution-item" key={execution.id}><div className="execution-heading"><strong><Icon name="phone" size={18} />{execution.device_id}</strong><Badge status={execution.status} /></div>{execution.error && <p className="execution-error">{execution.error}</p>}{execution.evidence?.steps?.length ? <details className="steps-disclosure"><summary>{t("Consulter les preuves ·")} {execution.evidence.steps.length} {t("étapes")}</summary><ul className="evidence-links">{execution.evidence.steps.map((step) => <li key={step.step_id}><span>{step.step_id.replace(/-/g, " ")}</span>{typeof step.screenshot === "string" ? <a href={`/api/control/console/executions/${execution.id}/captures/${encodeURIComponent(step.step_id)}`} target="_blank" rel="noopener noreferrer">{t("Ouvrir la capture")}<span className="sr-only"> {t("de")} {step.step_id}</span> ↗</a> : <span className="muted">{t("Aucune capture")}</span>}</li>)}</ul></details> : <p className="small-copy">{t("Les preuves apparaîtront lorsque le worker aura exécuté les étapes.")}</p>}</article>)}</div></section>
        <section><div className="surface-heading surface-heading--compact"><h3>{t("Journal des événements")}</h3><button className="text-button" disabled={eventLoading} onClick={() => void moreEvents(events.at(-1)?.sequence ?? 0)}><Icon name="refresh" size={16} />{t("Actualiser")}</button></div>{events.length ? <ol className="event-timeline">{events.map((event) => <li key={event.sequence}><span className="event-marker" /><div><strong>{t(eventLabels[event.type] ?? event.type)}</strong><span>{date(event.created_at, locale)}{typeof event.payload.step_id === "string" ? ` · ${event.payload.step_id}` : ""}</span></div></li>)}</ol> : <p className="small-copy">{t("Aucun événement disponible.")}</p>}{events.length >= 100 && <button className="text-button" disabled={eventLoading} onClick={() => void moreEvents(events.at(-1)?.sequence ?? 0)}>{t("Charger la suite du journal")}</button>}</section>
        {canCancel && (run.status === "queued" || run.status === "running") && !run.cancel_requested && <div className="cancel-zone">{confirmCancel ? <><p>{t("Arrêter cette exécution sur {count} appareil(s) ? Les actions déjà effectuées seront conservées.", { count: run.device_ids.length })}</p><div className="button-row"><button className="button button--secondary" disabled={busy} onClick={() => setConfirmCancel(false)}>{t("Revenir")}</button><button className="button button--danger" disabled={busy} onClick={() => void cancel()}>{busy ? t("Demande en cours…") : t("Confirmer l’arrêt")}</button></div></> : <button className="button button--danger-outline" onClick={() => setConfirmCancel(true)}>{t("Demander l’arrêt")}</button>}</div>}
      </>}
    </div>
  </Dialog>;
}
