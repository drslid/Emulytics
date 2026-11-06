"use client";

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
export function RunDetail({ runId, onClose, onChanged }: { runId: string; onClose: () => void; onChanged: () => void }) {
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
  return <Dialog title={run ? workflowName(run.workflow_id) : "Détail de l’exécution"} description={`Exécution ${runId.slice(0, 8)}`} onClose={onClose} wide>
    <div className="dialog-form">
      {error && <ErrorNotice message={error} />}
      {!run ? <p role="status" className="loading-copy">Chargement de l’exécution…</p> : <>
        <div className="run-detail-meta"><Badge status={run.status} cancelRequested={run.cancel_requested} /><span>{date(run.created_at)}</span><span>Version {run.workflow_version}</span></div>
        {run.cancel_requested && run.status === "running" && <div className="notice notice--warning">Arrêt demandé. Le worker doit encore confirmer sa fin ; l’appareil reste réservé jusque-là.</div>}
        {run.status === "needs_review" && <div className="notice notice--warning"><Icon name="warning" /><span>Une vérification est nécessaire avant de réutiliser l’appareil. Consultez les preuves ; aucune action incertaine ne sera relancée automatiquement.</span></div>}
        <section><h3 className="detail-section-title">Résultat par téléphone</h3><div className="execution-list">{run.executions.map((execution) => <article className="execution-item" key={execution.id}><div className="execution-heading"><strong><Icon name="phone" size={18} />{execution.device_id}</strong><Badge status={execution.status} /></div>{execution.error && <p className="execution-error">{execution.error}</p>}{execution.evidence?.steps?.length ? <details className="steps-disclosure"><summary>Consulter les preuves · {execution.evidence.steps.length} étapes</summary><ul className="evidence-links">{execution.evidence.steps.map((step) => <li key={step.step_id}><span>{step.step_id.replace(/-/g, " ")}</span>{typeof step.screenshot === "string" ? <a href={`/api/control/console/executions/${execution.id}/captures/${encodeURIComponent(step.step_id)}`} target="_blank" rel="noopener noreferrer">Ouvrir la capture<span className="sr-only"> de {step.step_id}</span> ↗</a> : <span className="muted">Aucune capture</span>}</li>)}</ul></details> : <p className="small-copy">Les preuves apparaîtront lorsque le worker aura exécuté les étapes.</p>}</article>)}</div></section>
        <section><div className="surface-heading surface-heading--compact"><h3>Journal des événements</h3><button className="text-button" disabled={eventLoading} onClick={() => void moreEvents(events.at(-1)?.sequence ?? 0)}><Icon name="refresh" size={16} />Actualiser</button></div>{events.length ? <ol className="event-timeline">{events.map((event) => <li key={event.sequence}><span className="event-marker" /><div><strong>{eventLabels[event.type] ?? event.type}</strong><span>{date(event.created_at)}{typeof event.payload.step_id === "string" ? ` · ${event.payload.step_id}` : ""}</span></div></li>)}</ol> : <p className="small-copy">Aucun événement disponible.</p>}{events.length >= 100 && <button className="text-button" disabled={eventLoading} onClick={() => void moreEvents(events.at(-1)?.sequence ?? 0)}>Charger la suite du journal</button>}</section>
        {(run.status === "queued" || run.status === "running") && !run.cancel_requested && <div className="cancel-zone">{confirmCancel ? <><p>Demander l’arrêt de cette exécution sur ses {run.device_ids.length} téléphone{run.device_ids.length > 1 ? "s" : ""} ? Les actions déjà effectuées seront conservées.</p><div className="button-row"><button className="button button--secondary" disabled={busy} onClick={() => setConfirmCancel(false)}>Revenir</button><button className="button button--danger" disabled={busy} onClick={() => void cancel()}>{busy ? "Demande en cours…" : "Confirmer l’arrêt"}</button></div></> : <button className="button button--danger-outline" onClick={() => setConfirmCancel(true)}>Demander l’arrêt</button>}</div>}
      </>}
    </div>
  </Dialog>;
}
