"use client";

import { useLocale } from "../../lib/i18n";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../lib/client-api";
import type { Page, RunDetail as Detail, RunEvent, Step, Workflow } from "../../lib/console-types";
import { Badge, Dialog, ErrorNotice, date, workflowName } from "./shared";
import { Icon } from "./icons";
import { LiveScreen } from "./live-screen";
import { ExecutionGallery } from "./execution-gallery";
import { RunDiagnosis } from "./run-diagnosis";
import { isExecutionLive, reconcileExecutionLive, toggleExecutionLive, type ExecutionLiveSelection } from "../../lib/execution-live";
import { runEditorPath } from "../../lib/run-authoring";

const eventLabels: Record<string, string> = {
  "run.created": "Demande enregistrée", "run.cancel_requested": "Arrêt demandé", "run.cancelled": "Exécution annulée",
  "execution.started": "Worker démarré", "execution.finished": "Exécution terminée", "execution.needs_review": "Vérification nécessaire",
  "action.intent": "Action préparée", "action.done": "Action confirmée", "action.failed": "Action échouée",
  "action.cancelled": "Action annulée", "action.uncertain": "Résultat de l’action incertain",
  "execution.step_completed": "Étape terminée"
};
export function RunDetail({ runId, onClose, onChanged, canCancel = true, canManageDevices = false, userId = "", canRetry = false, canEditRun = false, onOpen }: { runId: string; onClose: () => void; onChanged: () => void; canCancel?: boolean; canManageDevices?: boolean; userId?: string; canRetry?: boolean; canEditRun?: boolean; onOpen?: (id: string) => void }) {
  const { t, locale } = useLocale();
  const [liveSelection, setLiveSelection] = useState<ExecutionLiveSelection>({ executionId: null, hidden: false });
  const [workflowSteps, setWorkflowSteps] = useState<Step[] | undefined>();
  const [displayName, setDisplayName] = useState("");
  const [workflowUnavailable, setWorkflowUnavailable] = useState(false);
  const [run, setRun] = useState<Detail | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [eventLoading, setEventLoading] = useState(false);
  const requestSequence = useRef(0);
  const eventSequence = useRef(0);
  const eventCursor = useRef(0);
  const pendingDetail = useRef<number | null>(null);
  const pendingEvents = useRef<number | null>(null);
  const mounted = useRef(false);
  const mutating = useRef(false);
  const load = useCallback(async () => {
    if (!mounted.current || mutating.current || pendingDetail.current !== null) return;
    const request = ++requestSequence.current;
    pendingDetail.current = request;
    try {
      const detail = await api<Detail>(`runs/${runId}`);
      if (request === requestSequence.current && !mutating.current) { setRun(detail); setError(""); }
    } catch (failure) { if (request === requestSequence.current && !mutating.current) setError((failure as Error).message); }
    finally { if (pendingDetail.current === request) pendingDetail.current = null; }
  }, [runId]);
  const moreEvents = useCallback(async (after: number) => {
    if (!mounted.current || mutating.current || pendingEvents.current !== null) return;
    const request = ++eventSequence.current;
    pendingEvents.current = request;
    setEventLoading(true);
    try {
      const page = await api<Page<RunEvent>>(`runs/${runId}/events?after=${after}&limit=100`);
      if (request !== eventSequence.current || mutating.current) return;
      eventCursor.current = Math.max(eventCursor.current, ...page.items.map(event => event.sequence));
      setEvents(current => [...new Map([...current, ...page.items].map(event => [event.sequence, event])).values()].sort((left, right) => left.sequence - right.sequence));
    } catch (failure) { if (request === eventSequence.current && !mutating.current) setError((failure as Error).message); }
    finally { if (pendingEvents.current === request) { pendingEvents.current = null; setEventLoading(false); } }
  }, [runId]);
  useEffect(() => {
    mounted.current = true;
    setRun(null); setEvents([]); setError(""); setWorkflowSteps(undefined);
    setLiveSelection({ executionId: null, hidden: false });
    eventCursor.current = 0;
    void load(); void moreEvents(0);
    return () => { mounted.current = false; requestSequence.current++; eventSequence.current++; pendingDetail.current = null; pendingEvents.current = null; };
  }, [load, moreEvents]);
  const pollingInterval = !run || run.status === "queued" || run.status === "running" || run.executions.some(isExecutionLive) ? 2000 : 5000;
  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState === "visible") { void load(); void moreEvents(eventCursor.current); }
      else { requestSequence.current++; eventSequence.current++; pendingDetail.current = null; pendingEvents.current = null; setEventLoading(false); }
    };
    const timer = setInterval(() => { if (document.visibilityState === "visible") refresh(); }, pollingInterval);
    document.addEventListener("visibilitychange", refresh);
    return () => { clearInterval(timer); document.removeEventListener("visibilitychange", refresh); };
  }, [load, moreEvents, pollingInterval]);
  useEffect(() => {
    setLiveSelection(current => {
      const next = reconcileExecutionLive(run?.executions ?? [], current);
      return next.executionId === current.executionId && next.hidden === current.hidden ? current : next;
    });
  }, [run?.executions]);
  const live = reconcileExecutionLive(run?.executions ?? [], liveSelection);
  const screenExecutionId = live.hidden ? null : live.executionId;
  async function cancel() {
    if (mutating.current) return;
    mutating.current = true;
    const request = ++requestSequence.current;
    eventSequence.current++; pendingDetail.current = null; pendingEvents.current = null;
    setEventLoading(false);
    setBusy(true); setError("");
    try { const result = await api<Detail>(`runs/${runId}/cancel`, {}); if (mounted.current && request === requestSequence.current) { requestSequence.current++; setRun(result); setConfirmCancel(false); } onChanged(); }
    catch (failure) { if (mounted.current && request === requestSequence.current) setError((failure as Error).message); }
    finally { mutating.current = false; if (mounted.current) { setBusy(false); void moreEvents(eventCursor.current); } }
  }
  const workflowId = run?.workflow_id, workflowVersion = run?.workflow_version;
  useEffect(() => {
    if (!workflowId || !workflowVersion) return;
    let active = true;
    setWorkflowUnavailable(false); setWorkflowSteps(undefined); setDisplayName("");
    void api<Workflow>(`workflows/${encodeURIComponent(workflowId)}/versions/${workflowVersion}`)
      .then(workflow => { if (active) {setWorkflowSteps(workflow.steps); setDisplayName(workflow.name ?? "");} })
      .catch(() => { if (active) setWorkflowUnavailable(true); });
    return () => { active = false; };
  }, [workflowId, workflowVersion]);
  return <Dialog title={displayName || (run ? t(workflowName(run.workflow_id)) : t("Détail de l’exécution"))} description={t("Exécution {id}", { id: runId.slice(0, 8) })} onClose={onClose} wide className="console-dialog--execution">
    <div className="dialog-form">
      {error && <ErrorNotice message={error} />}
      {!run ? <p role="status" className="loading-copy">{t("Chargement de l’exécution…")}</p> : <>
        <div className="run-detail-meta"><Badge status={run.status} cancelRequested={run.cancel_requested} /><span>{date(run.created_at, locale)}</span><span>{t("Version")} {run.workflow_version}</span>
          {canEditRun && !workflowUnavailable && !run.workflow_id.startsWith("emulator-system-") && <a className="button button--secondary run-edit-action" href={`${runEditorPath}?source=${encodeURIComponent(run.id)}`}>{t("Modifier et relancer")}</a>}
        </div>
        {run.status === "queued" && <div className="notice notice--info"><Icon name="clock" /><span>{t("Le worker doit être actif sur chaque hôte. Les téléphones occupés attendront leur tour ; une inscription ne confirme pas une connexion Android.")} <a href="/monitoring">{t("Monitoring")}</a></span></div>}
        {run.cancel_requested && run.status === "running" && <div className="notice notice--warning">{t("Arrêt demandé. Le worker doit encore confirmer sa fin ; l’appareil reste réservé jusque-là.")}</div>}
        {run.status === "needs_review" && <div className="notice notice--warning"><Icon name="warning" /><span>{t("Une vérification est nécessaire avant de réutiliser l’appareil. Consultez les preuves ; aucune action incertaine ne sera relancée automatiquement.")}</span></div>}
        <RunDiagnosis key={`${userId}:${run.id}`} run={run} userId={userId} canRetry={canRetry} onOpen={onOpen ?? (() => {})} onChanged={onChanged} />
        <section>
          <h3 className="detail-section-title">{t("Résultat par téléphone")}</h3>
          {run.executions.filter(isExecutionLive).length > 1 && <p className="small-copy execution-live-help">{t("Un seul écran est affiché à la fois. Choisissez un autre téléphone pour changer le direct.")}</p>}
          {workflowUnavailable && <p className="small-copy">{t("Le détail des étapes prévues est indisponible. Les captures collectées restent accessibles.")}</p>}
          <div className="execution-list">{run.executions.map((execution) => <article className="execution-item" key={execution.id}>
            <div className="execution-heading"><strong><Icon name="phone" size={18} /><bdi>{execution.device_id}</bdi></strong><Badge status={execution.status} /></div>
            {execution.attempt > 1 && <p className="small-copy">{t("Tentative {n}", { n: execution.attempt })}</p>}
            {execution.error && <p className="execution-error">{execution.error}</p>}
            {isExecutionLive(execution) && <button type="button" className="text-button execution-live-toggle" aria-expanded={screenExecutionId === execution.id} aria-controls={`live-screen-${execution.id}`} onClick={() => setLiveSelection(current => toggleExecutionLive(run.executions, current, execution.id))}><Icon name="phone" size={16} />{t(screenExecutionId === execution.id ? "Masquer l’écran" : "Voir en direct")}</button>}
            <div className={`execution-watch-layout ${screenExecutionId === execution.id ? "execution-watch-layout--live" : ""}`}>
              {screenExecutionId === execution.id && <aside className="execution-live-panel" id={`live-screen-${execution.id}`} aria-label={t("Écran en direct")} key="live"><h4>{t("Écran en direct")}</h4><LiveScreen key={execution.id} deviceId={execution.device_id} executionId={execution.id} name={execution.device_id} /></aside>}
              <ExecutionGallery key="gallery" execution={execution} steps={workflowSteps} compact={screenExecutionId === execution.id} />
            </div>
          </article>)}</div>
        </section>
        <section><div className="surface-heading surface-heading--compact"><h3>{t("Journal des événements")}</h3><button className="text-button" disabled={eventLoading} onClick={() => void moreEvents(events.at(-1)?.sequence ?? 0)}><Icon name="refresh" size={16} />{t("Actualiser")}</button></div>{events.length ? <ol className="event-timeline" tabIndex={0} aria-label={t("Journal des événements")}>{events.map((event) => <li key={event.sequence}><span className="event-marker" /><div><strong>{t(eventLabels[event.type] ?? event.type)}</strong><span>{date(event.created_at, locale)}{typeof event.payload.step_id === "string" ? ` · ${event.payload.step_id}` : ""}</span></div></li>)}</ol> : <p className="small-copy">{t("Aucun événement disponible.")}</p>}{events.length >= 100 && <button className="text-button" disabled={eventLoading} onClick={() => void moreEvents(events.at(-1)?.sequence ?? 0)}>{t("Charger la suite du journal")}</button>}</section>
        {canCancel && (canManageDevices || !run.workflow_id.startsWith('emulator-system-')) && (run.status === "queued" || run.status === "running") && !run.cancel_requested && <div className="cancel-zone">{confirmCancel ? <><p>{t("Arrêter cette exécution sur {count} appareil(s) ? Les actions déjà effectuées seront conservées.", { count: run.device_ids.length })}</p><div className="button-row"><button className="button button--secondary" disabled={busy} onClick={() => setConfirmCancel(false)}>{t("Revenir")}</button><button className="button button--danger" disabled={busy} onClick={() => void cancel()}>{busy ? t("Demande en cours…") : t("Confirmer l’arrêt")}</button></div></> : <button className="button button--danger-outline" onClick={() => setConfirmCancel(true)}>{t("Demander l’arrêt")}</button>}</div>}
      </>}
    </div>
  </Dialog>;
}
