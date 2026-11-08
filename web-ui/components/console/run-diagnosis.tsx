"use client";

import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../lib/client-api";
import { useT } from "../../lib/i18n";
import type { RunDetail } from "../../lib/console-types";
import { diagnosisMessage, parseRetryDraft, retryKey, type RetryDraft } from "../../lib/run-recovery";
import { ErrorNotice } from "./shared";

type Diagnosis = {source_run_id: string | null; active_retry_id: string | null; items: {execution_id: string; device_id: string; code: string; failed_step: string | null; last_capture_step: string | null; can_retry: boolean; retry_block: string | null}[]};

export function RunDiagnosis({ run, userId, canRetry, onOpen, onChanged }: {run: RunDetail; userId: string; canRetry: boolean; onOpen: (id: string) => void; onChanged: () => void}) {
  const t = useT();
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null), [error, setError] = useState("");
  const [pending, setPending] = useState<RetryDraft | null>(null), [confirm, setConfirm] = useState<RetryDraft | null>(null), [busy, setBusy] = useState(false);
  const sending = useRef(false);
  useEffect(() => {
    let active = true;
    void api<Diagnosis>(`runs/${run.id}/diagnosis`).then(value => {if (active) {setDiagnosis(value); setError("");}}).catch(failure => {if (active) setError(failure.message);});
    return () => {active = false;};
  }, [run.id, run.updated_at]);
  useEffect(() => {
    try {const raw = sessionStorage.getItem(retryKey(userId, run.id)); if (raw) {const draft = parseRetryDraft(JSON.parse(raw)); if (draft) {setPending(draft); setConfirm(draft);}}}
    catch {setError(t("Votre navigateur ne permet pas de conserver une demande en cours. Autorisez le stockage de session avant de lancer."));}
  }, [run.id, userId, t]);
  const eligible = diagnosis?.items.filter(item => item.can_retry).map(item => item.device_id) ?? [];
  async function retry() {
    if (sending.current || (!pending && !confirm)) return;
    sending.current = true; setBusy(true); setError("");
    const draft = pending ?? confirm!;
    try {
      sessionStorage.setItem(retryKey(userId, run.id), JSON.stringify(draft)); setPending(draft);
      const next = await api<RunDetail>(`runs/${run.id}/retry`, draft);
      sessionStorage.removeItem(retryKey(userId, run.id)); setPending(null); setConfirm(null);
      onChanged(); onOpen(next.id);
    } catch (failure) {
      if (failure instanceof ApiError && [401,403,404,409,422].includes(failure.status)) {try {sessionStorage.removeItem(retryKey(userId, run.id));} catch {} setPending(null);}
      setError((failure as Error).message);
    } finally {sending.current = false; setBusy(false);}
  }
  const failed = diagnosis?.items.filter(item => !["queued", "running", "leased", "succeeded", "cancelled"].includes(item.code)) ?? [];
  if (!failed.length && !diagnosis?.source_run_id && !pending && !error) return null;
  return <section className="review-section" aria-label={t("Diagnostic et relance")}><h3>{t("Diagnostic et relance")}</h3>
    {error && <ErrorNotice message={error} />}
    {diagnosis?.source_run_id && <button type="button" className="text-button" onClick={() => onOpen(diagnosis.source_run_id!)}>{t("Voir l’exécution d’origine")}</button>}
    {failed.map(item => <div key={item.execution_id}><strong><bdi>{item.device_id}</bdi></strong><p>{t(diagnosisMessage(item.code))}</p>{item.failed_step && <p className="small-copy">{t("Étape concernée")} : <bdi>{item.failed_step}</bdi></p>}{item.last_capture_step && <a href={`#capture-${item.execution_id}-${item.last_capture_step}`}>{t("Consulter les captures")}</a>}{item.retry_block && <p className="small-copy">{t("La relance est bloquée si un effet est incertain, si l’appareil est réservé ou si le parcours contient des actions non répétables.")}</p>}</div>)}
    {diagnosis?.active_retry_id && <button type="button" className="button button--secondary" onClick={() => onOpen(diagnosis.active_retry_id!)}>{t("Voir la relance en cours")}</button>}
    {canRetry && (eligible.length > 0 || pending || confirm) && <div className="button-row">{confirm ? <><p>{t("La relance recommence le parcours uniquement sur ces appareils : {names}.", {names: (pending?.device_ids ?? confirm.device_ids).join(", ")})}</p><button type="button" className="button button--primary" disabled={busy} onClick={() => void retry()}>{t(pending ? "Confirmer le résultat de la demande" : "Confirmer la relance")}</button>{!pending && <button type="button" className="text-button" disabled={busy} onClick={() => setConfirm(null)}>{t("Annuler")}</button>}</> : <button type="button" className="button button--primary" onClick={() => setConfirm({request_id: crypto.randomUUID(), device_ids: [...eligible]})}>{t("Relancer les échecs admissibles")}</button>}</div>}
  </section>;
}
