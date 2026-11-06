"use client";

import { useLocale } from "../../lib/i18n";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../lib/client-api";
import type { Page, RunDetail as Detail, RunEvent, Step, Workflow } from "../../lib/console-types";
import { Badge, Dialog, ErrorNotice, date, workflowName } from "./shared";
import { Icon } from "./icons";
import { LiveScreen } from "./live-screen";
import { ExecutionGallery } from "./execution-gallery";

const eventLabels: Record<string, string> = {
  "run.created": "Demande enregistrée", "run.cancel_requested": "Arrêt demandé", "run.cancelled": "Exécution annulée",
  "execution.started": "Worker démarré", "execution.finished": "Exécution terminée", "execution.needs_review": "Vérification nécessaire",
  "action.intent": "Action préparée", "action.done": "Action confirmée", "action.failed": "Action échouée",
  "action.cancelled": "Action annulée", "action.uncertain": "Résultat de l’action incertain",
  "execution.step_completed": "Étape terminée"
};
export function RunDetail({ runId, onClose, onChanged, canCancel = true }: { runId: string; onClose: () => void; onChanged: () => void; canCancel?: boolean }) {
  const { t, locale } = useLocale();
  const [screenExecutionId, setScreenExecutionId] = useState<string | null>(null);
  const [workflowSteps, setWorkflowSteps] = useState<Step[] | undefined>();
  const [workflowUnavailable, setWorkflowUnavailable] = useState(false);
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
  const workflowId = run?.workflow_id, workflowVersion = run?.workflow_version;
  useEffect(() => {
    if (!workflowId || !workflowVersion) return;
    let active = true;
    setWorkflowUnavailable(false); setWorkflowSteps(undefined);
    void api<Workflow>(`workflows/${encodeURIComponent(workflowId)}/versions/${workflowVersion}`)
      .then(workflow => { if (active) setWorkflowSteps(workflow.steps); })
      .catch(() => { if (active) setWorkflowUnavailable(true); });
    return () => { active = false; };
  }, [workflowId, workflowVersion]);
  return <Dialog title={run ? t(workflowName(run.workflow_id)) : t("Détail de l’exécution")} description={t("Exécution {id}", { id: runId.slice(0, 8) })} onClose={onClose} wide className="console-dialog--execution">
    <div className="dialog-form">
      {error && <ErrorNotice message={error} />}
      {!run ? <p role="status" className="loading-copy">{t("Chargement de l’exécution…")}</p> : <>
        <div className="run-detail-meta"><Badge status={run.status} cancelRequested={run.cancel_requested} /><span>{date(run.created_at, locale)}</span><span>{t("Version")} {run.workflow_version}</span></div>
        {run.status === "queued" && <div className="notice notice--info"><Icon name="clock" /><span>{t("Le worker doit être actif sur chaque hôte. Les téléphones occupés attendront leur tour ; une inscription ne confirme pas une connexion Android.")} <a href="/monitoring">{t("Monitoring")}</a></span></div>}
        {run.cancel_requested && run.status === "running" && <div className="notice notice--warning">{t("Arrêt demandé. Le worker doit encore confirmer sa fin ; l’appareil reste réservé jusque-là.")}</div>}
        {run.status === "needs_review" && <div className="notice notice--warning"><Icon name="warning" /><span>{t("Une vérification est nécessaire avant de réutiliser l’appareil. Consultez les preuves ; aucune action incertaine ne sera relancée automatiquement.")}</span></div>}
        <section>
          <h3 className="detail-section-title">{t("Résultat par téléphone")}</h3>
          {workflowUnavailable && <p className="small-copy">{t("Le détail des étapes prévues est indisponible. Les captures collectées restent accessibles.")}</p>}
          <div className="execution-list">{run.executions.map((execution) => <article className="execution-item" key={execution.id}>
            <div className="execution-heading"><strong><Icon name="phone" size={18} /><bdi>{execution.device_id}</bdi></strong><Badge status={execution.status} /></div>
            {execution.attempt > 1 && <p className="small-copy">{t("Tentative {n}", { n: execution.attempt })}</p>}
            {execution.error && <p className="execution-error">{execution.error}</p>}
            <ExecutionGallery execution={execution} steps={workflowSteps} />
            <button className="text-button execution-live-toggle" aria-expanded={screenExecutionId === execution.id} aria-controls={`live-screen-${execution.id}`} onClick={() => setScreenExecutionId(current => current === execution.id ? null : execution.id)}><Icon name="phone" size={16} />{t(screenExecutionId === execution.id ? "Masquer l’écran" : "Voir en direct")}</button>
            {screenExecutionId === execution.id && <div id={`live-screen-${execution.id}`}><p className="small-copy">{t("Le direct montre l’appareil maintenant. Les captures ci-dessus conservent les étapes du parcours.")}</p><LiveScreen deviceId={execution.device_id} name={execution.device_id} /></div>}
          </article>)}</div>
        </section>
        <section><div className="surface-heading surface-heading--compact"><h3>{t("Journal des événements")}</h3><button className="text-button" disabled={eventLoading} onClick={() => void moreEvents(events.at(-1)?.sequence ?? 0)}><Icon name="refresh" size={16} />{t("Actualiser")}</button></div>{events.length ? <ol className="event-timeline" tabIndex={0} aria-label={t("Journal des événements")}>{events.map((event) => <li key={event.sequence}><span className="event-marker" /><div><strong>{t(eventLabels[event.type] ?? event.type)}</strong><span>{date(event.created_at, locale)}{typeof event.payload.step_id === "string" ? ` · ${event.payload.step_id}` : ""}</span></div></li>)}</ol> : <p className="small-copy">{t("Aucun événement disponible.")}</p>}{events.length >= 100 && <button className="text-button" disabled={eventLoading} onClick={() => void moreEvents(events.at(-1)?.sequence ?? 0)}>{t("Charger la suite du journal")}</button>}</section>
        {canCancel && (run.status === "queued" || run.status === "running") && !run.cancel_requested && <div className="cancel-zone">{confirmCancel ? <><p>{t("Arrêter cette exécution sur {count} appareil(s) ? Les actions déjà effectuées seront conservées.", { count: run.device_ids.length })}</p><div className="button-row"><button className="button button--secondary" disabled={busy} onClick={() => setConfirmCancel(false)}>{t("Revenir")}</button><button className="button button--danger" disabled={busy} onClick={() => void cancel()}>{busy ? t("Demande en cours…") : t("Confirmer l’arrêt")}</button></div></> : <button className="button button--danger-outline" onClick={() => setConfirmCancel(true)}>{t("Demander l’arrêt")}</button>}</div>}
      </>}
    </div>
  </Dialog>;
}
