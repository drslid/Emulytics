"use client";

import { useLocale } from "../../lib/i18n";

import { useEffect, useRef, useState, type FormEvent } from "react";
import type { Device, RunDetail, Workflow } from "../../lib/console-types";
import { draftKey, parseRunDraft, type RunSubmission } from "../../lib/run-draft";
import { ApiError, api } from "../../lib/client-api";
import { Badge, Dialog, ErrorNotice, workflowName } from "./shared";
import { Icon } from "./icons";
import { DeviceConnection } from "./device-connection";
import { canSubmitDevices, isDeviceReady } from "../../lib/device-readiness";

export function RunDialog({ userId, devices, workflows, initialDeviceIds, initialWorkflow, onClose, onLaunched }: {
  userId: string; devices: Device[]; workflows: Workflow[]; initialDeviceIds: string[]; initialWorkflow?: Workflow;
  onClose: () => void; onLaunched: (run: RunDetail) => void;
}) {
  const { t, locale } = useLocale();
  const [deletedKeys, setDeletedKeys] = useState<Set<string>>(() => new Set());
  const availableWorkflows = (initialWorkflow && !workflows.some(item => item.workflow_id === initialWorkflow.workflow_id && item.version === initialWorkflow.version) ? [initialWorkflow, ...workflows] : workflows)
    .filter(item => !deletedKeys.has(`${item.workflow_id}:${item.version}`));
  const [workflowKey, setWorkflowKey] = useState(initialWorkflow ? `${initialWorkflow.workflow_id}:${initialWorkflow.version}` : "");
  const [ids, setIds] = useState(initialDeviceIds);
  const [concurrency, setConcurrency] = useState(1);
  const [search, setSearch] = useState("");
  const [review, setReview] = useState<RunSubmission | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const attempted = useRef(false);
  useEffect(() => {
    try {
      const saved = sessionStorage.getItem(draftKey(userId));
      const pending = saved ? parseRunDraft(JSON.parse(saved)) : null;
      if (pending) { setReview(pending); setWorkflowKey(`${pending.workflow_id}:${pending.workflow_version}`); attempted.current = true; }
    } catch { setError(t("Votre navigateur ne permet pas de conserver une demande en cours. Autorisez le stockage de session avant de lancer.")); }
  }, [userId]);
  useEffect(() => {
    if (!attempted.current) setIds((current) => current.filter((id) => isDeviceReady(devices.find((device) => device.device_id === id))));
  }, [devices]);
  const blocked = !!review && !canSubmitDevices(review.device_ids, devices);
  const unavailable = devices.filter(device => !isDeviceReady(device));
  const workflow = availableWorkflows.find((item) => `${item.workflow_id}:${item.version}` === workflowKey);
  const visible = devices.filter((device) => (device.display_name || device.device_id).toLocaleLowerCase(locale).includes(search.toLocaleLowerCase(locale)));
  function prepare(event: FormEvent) {
    event.preventDefault();
    if (!workflow || !ids.length || !Number.isInteger(concurrency) || concurrency < 1 || concurrency > ids.length || !canSubmitDevices(ids, devices)) return;
    setReview({ workflow_id: workflow.workflow_id, workflow_version: workflow.version, device_ids: [...ids], max_concurrency: concurrency, parameters: {}, idempotency_key: crypto.randomUUID() });
    setError("");
  }
  async function launch() {
    if (!review || busy || (blocked && !attempted.current)) return;
    setBusy(true); setError("");
    try {
      sessionStorage.setItem(draftKey(userId), JSON.stringify(review));
      attempted.current = true;
      const run = await api<RunDetail>("runs", review);
      try { sessionStorage.removeItem(draftKey(userId)); } catch { /* The same key still safely replays the recorded result. */ }
      onLaunched(run);
    } catch (failure) {
      if (failure instanceof ApiError && [401, 403, 404, 410, 422].includes(failure.status)) {
        try { sessionStorage.removeItem(draftKey(userId)); } catch { /* No request was accepted. */ }
        attempted.current = false;
        if (failure.status === 410) {
          setDeletedKeys(current => new Set([...current, `${review.workflow_id}:${review.workflow_version}`]));
          setWorkflowKey(""); setReview(null);
        }
      }
      setError(attempted.current ? (failure as Error).message + t(" La demande est conservée : réessayez pour vérifier son résultat sans créer de doublon.") : failure instanceof ApiError ? failure.message : t("Votre navigateur empêche de conserver la demande. Aucun lancement n’a été envoyé. Autorisez le stockage de session pour continuer."));
    }
    finally { setBusy(false); }
  }
  return <Dialog title={review ? t("Vérifier le lancement") : t("Lancer une automatisation")} description={review ? t("Ce lot sera conservé pour toute l’exécution.") : t("Un parcours, une sélection de téléphones, un résultat traçable.")} onClose={() => { if (!busy) onClose(); }} wide>
    {error && <div className="dialog-notice"><ErrorNotice message={error} /></div>}
    {review ? <div className="dialog-form">
      {attempted.current && <div className="notice notice--warning">{t("Une demande précédente doit être confirmée. Ce bouton vérifie la même demande ; il ne crée pas un nouveau lot. Vous pouvez fermer cette fenêtre et la retrouver après connexion.")}</div>}
      {blocked && !attempted.current && <ErrorNotice message={t("Un appareil sélectionné n’est plus prêt. Vérifiez sa connexion avant de lancer.")} />}
      <div className="review-section"><span className="eyebrow">{t("Automatisation")}</span><h3>{workflow?.name || t(workflowName(review.workflow_id))}</h3><p>{t("Version")} {review.workflow_version} · {workflow?.steps.length} {t("étapes")}</p></div>
      <div className="review-section"><span className="eyebrow">{t("Téléphones ciblés ·")} {review.device_ids.length}</span><div className="device-chips">{review.device_ids.map((id) => <span key={id}><Icon name="phone" size={16} />{devices.find(device => device.device_id === id)?.display_name || id}</span>)}</div></div>
      <div className="review-section"><span className="eyebrow">{t("Exécution")}</span><p>{t("{count} appareil(s) à la fois. Chaque appareil dispose de son propre journal et de ses preuves.", {count: review.max_concurrency})}</p></div>
      <div className="notice notice--info"><Icon name="clock" /><span>{t("Le worker doit être actif sur chaque hôte. Les téléphones occupés attendront leur tour ; une inscription ne confirme pas une connexion Android.")}</span></div>
      <div className="dialog-footer"><button className="button button--secondary" disabled={busy || attempted.current} onClick={() => setReview(null)}>{t("Modifier")}</button><button className="button button--primary" disabled={busy || (blocked && !attempted.current)} onClick={() => void launch()}><Icon name="play" size={18} />{busy ? t("Envoi en cours…") : (attempted.current ? t("Confirmer le résultat de la demande") : t("Confirmer le lancement"))}</button></div>
    </div> : <form className="dialog-form" onSubmit={prepare}>
      <label>{t("1. Choisir l’automatisation")}<select required value={workflowKey} onChange={(event) => setWorkflowKey(event.target.value)}><option value="" disabled>{t("Sélectionner un parcours")}</option>{availableWorkflows.map((item) => <option key={`${item.workflow_id}:${item.version}`} value={`${item.workflow_id}:${item.version}`}>{item.name || t(workflowName(item.workflow_id))} · v{item.version}</option>)}</select></label>
      {unavailable.length > 0 && <div className="notice notice--warning"><span>{t("Connexion Android requise pour lancer un parcours.")} {t("Appareils indisponibles : {names}.", { names: unavailable.map(device => device.display_name || device.device_id).join(", ") })}</span><a href="/monitoring">{t("Vérifier le monitoring")}</a></div>}
      {!availableWorkflows.length && <div className="notice notice--info">{t("Aucun parcours publié")}</div>}
      <fieldset className="device-picker"><legend>{t("2. Cibler les téléphones")} <span>{t("{count} sélectionné(s)", {count: ids.length})}</span></legend><input type="search" aria-label={t("Filtrer les téléphones proposés")} placeholder={t("Rechercher dans les téléphones chargés…")} value={search} onChange={(event) => setSearch(event.target.value)} /><div className="device-picker-list">{visible.length ? visible.map((device) => <label key={device.device_id} className="device-picker-row"><input type="checkbox" checked={ids.includes(device.device_id)} disabled={!isDeviceReady(device) || (!ids.includes(device.device_id) && ids.length >= 100)} onChange={() => setIds((current) => current.includes(device.device_id) ? current.filter((id) => id !== device.device_id) : [...current, device.device_id])} /><span><strong>{device.display_name || device.device_id}</strong><small>{device.host_id} · {device.serial} · {device.kind === "emulator" ? t("Émulateur") : t("Physique")}</small></span><>{device.availability === "needs_review" ? <Badge status="needs_review" /> : <DeviceConnection device={device} />}</></label>) : <p className="picker-empty">{t("Aucun téléphone à proposer. Ajoutez un appareil dans Téléphones.")}</p>}</div></fieldset>
      <label>{t("Téléphones exécutés en parallèle")}<input type="number" required min={1} max={Math.max(1, ids.length)} value={concurrency} onChange={(event) => setConcurrency(Number(event.target.value))} /><span>{t("De 1 à {count}, dans la limite de votre sélection.", {count: Math.max(1, ids.length)})}</span></label>
      <div className="dialog-footer"><button type="button" className="button button--secondary" onClick={onClose}>{t("Annuler")}</button><button className="button button--primary" disabled={!workflow || !canSubmitDevices(ids, devices) || concurrency < 1 || concurrency > ids.length}>{t("Vérifier le lancement")}<Icon name="arrow" size={18} /></button></div>
    </form>}
  </Dialog>;
}
