"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { api, ApiError } from "../../lib/client-api";
import type { Device } from "../../lib/console-types";
import { isDeviceReady } from "../../lib/device-readiness";
import { canonicalizeEmulatorUpload, emulatorCanLaunch, emulatorCanManage, emulatorConnectionDevice, emulatorIntentKey, emulatorOperationActive, MAX_APK_BYTES, missingEmulatorApplications, parseEmulatorCreation, parseEmulatorOperation, selectEmulatorApplication, type EmulatorAction, type EmulatorApplication, type EmulatorCatalog, type EmulatorCreation, type EmulatorOperation, type ManagedEmulator } from "../../lib/emulators";
import { useLocale } from "../../lib/i18n";
import { Badge, Dialog, ErrorNotice, date } from "./shared";
import { Icon } from "./icons";
import { DEFAULT_HARDWARE, hardwareEditable, parseHardware, sameAppliedHardware, sameHardware, type EmulatorHardware } from "../../lib/emulator-hardware";
import { hardwareCopy, hardwareStorageCopy } from "../../lib/emulator-hardware-copy";
import { EmulatorHardwareFields, HardwareSummary } from "./emulator-hardware-fields";
import { FDroidPicker } from "./fdroid-picker";

const labels = { created: "À préparer", starting: "Démarrage en cours", running: "Allumé · à préparer", ready: "Prêt", stopped: "Arrêté", preparing: "Préparation en cours", failed: "Échec de préparation", unknown: "État non confirmé" };
const definite = (failure: unknown) => failure instanceof ApiError && [401, 403, 404, 409, 422].includes(failure.status);
const storageError = "Autorisez le stockage de session du navigateur pour sécuriser cette demande.";
const emulatorPlatform = "Android 10 · x86_64";

export function ManagedEmulators({ userId, devices, canManage, canLaunch, onChanged, onLaunch, onOpenRun, onDevices }: {
  userId: string; devices: Device[]; canManage: boolean; canLaunch: boolean; onChanged: () => void; onLaunch: (device: Device) => void; onOpenRun: (runId: string) => void; onDevices: (devices: Device[]) => void;
}) {
  const { t } = useLocale();
  const [catalog, setCatalog] = useState<EmulatorCatalog | null>(null), [error, setError] = useState("");
  const [creating, setCreating] = useState(false), [selected, setSelected] = useState<string | null>(null);
  const [sending, setSending] = useState<string[]>([]), [pending, setPending] = useState<Record<string, EmulatorOperation>>({}), [operationErrors, setOperationErrors] = useState<Record<string, string>>({});
  const intents = useRef<Record<string, EmulatorOperation>>({}), inFlight = useRef(new Set<string>()), mounted = useRef(false);
  const sequence = useRef(0), loading = useRef<number | null>(null);
  const load = useCallback(async () => {
    if (!mounted.current || loading.current !== null || document.visibilityState === "hidden") return;
    const request = ++sequence.current; loading.current = request;
    try {
      const result = await api<EmulatorCatalog>("console/emulators");
      if (request !== sequence.current || !mounted.current) return;
      if (!Array.isArray(result.items) || !Array.isArray(result.applications) || !Array.isArray(result.hosts)) throw new Error();
      setCatalog(result); setError("");
      if (canManage) {
        for (const emulator of result.items) {
          if (intents.current[emulator.device_id]) continue;
          try { const raw = sessionStorage.getItem(emulatorIntentKey(userId, emulator.device_id)); const saved = raw ? parseEmulatorOperation(JSON.parse(raw)) : null; if (saved) intents.current[emulator.device_id] = saved; } catch { /* A new request still checks persistence before being sent. */ }
        }
        setPending({ ...intents.current });
      }
    } catch (failure) { if (request === sequence.current && mounted.current) setError(failure instanceof ApiError ? failure.message : t("La liste des émulateurs est indisponible. Réessayez.")); }
    finally { if (loading.current === request) loading.current = null; }
  }, [userId, canManage, t]);
  useEffect(() => { mounted.current = true; void load(); return () => { mounted.current = false; sequence.current++; loading.current = null; }; }, [load]);
  useEffect(() => { onDevices(error ? [] : (catalog?.items ?? []).flatMap(emulator => emulator.device?.device_id === emulator.device_id ? [emulator.device] : [])); }, [catalog?.items, error, onDevices]);
  const active = catalog?.items.some(emulatorOperationActive) ?? false;
  useEffect(() => {
    const visible = () => { if (document.visibilityState === "hidden") { sequence.current++; loading.current = null; } else void load(); };
    const timer = setInterval(() => void load(), active ? 2000 : 5000);
    document.addEventListener("visibilitychange", visible);
    return () => { clearInterval(timer); document.removeEventListener("visibilitychange", visible); };
  }, [load, active]);
  function changed(emulator?: ManagedEmulator) {
    sequence.current++; loading.current = null;
    if (emulator) setCatalog(current => current ? { ...current, items: current.items.some(item => item.device_id === emulator.device_id) ? current.items.map(item => item.device_id === emulator.device_id ? emulator : item) : [...current.items, emulator] } : current);
    onChanged(); void load();
  }
  function uploaded(application: EmulatorApplication) {
    sequence.current++; loading.current = null;
    setCatalog(current => current ? { ...current, applications: [...current.applications.filter(item => item.id !== application.id), application] } : current);
    void load();
  }
  async function operate(emulator: ManagedEmulator, action: EmulatorAction) {
    const id = emulator.device_id;
    if (!canManage || inFlight.current.has(id)) return;
    const previous = intents.current[id];
    if (!previous && !emulatorCanManage(emulator, action, catalog?.applications ?? [])) return;
    const intent = previous ?? { action, idempotency_key: crypto.randomUUID() };
    let sent = false;
    inFlight.current.add(id); setSending([...inFlight.current]); setOperationErrors(current => ({ ...current, [id]: "" }));
    try {
      sessionStorage.setItem(emulatorIntentKey(userId, id), JSON.stringify(intent));
      intents.current[id] = intent; setPending({ ...intents.current }); sent = true;
      const result = await api<{ run_id: string; emulator: ManagedEmulator }>(`console/emulators/${encodeURIComponent(id)}/${intent.action}`, { idempotency_key: intent.idempotency_key });
      sessionStorage.removeItem(emulatorIntentKey(userId, id)); delete intents.current[id];
      if (mounted.current) { setPending({ ...intents.current }); changed(result.emulator); }
    } catch (failure) {
      if (!sent || definite(failure)) { try { sessionStorage.removeItem(emulatorIntentKey(userId, id)); } catch {} delete intents.current[id]; }
      if (mounted.current) { setPending({ ...intents.current }); setOperationErrors(current => ({ ...current, [id]: !sent ? t(storageError) : (failure instanceof ApiError ? failure.message : t("Le service est indisponible. Réessayez dans un instant.")) })); }
    } finally { inFlight.current.delete(id); if (mounted.current) setSending([...inFlight.current]); }
  }
  const current = catalog?.items.find(item => item.device_id === selected);
  const launchReady = (emulator: ManagedEmulator) => emulatorCanLaunch(emulator, isDeviceReady(emulatorConnectionDevice(emulator, devices)));
  const actions = (emulator: ManagedEmulator) => <EmulatorActions emulator={emulator} applications={catalog?.applications ?? []} canManage={canManage && !!catalog?.enabled} canLaunch={canLaunch} ready={launchReady(emulator)} sending={sending.includes(emulator.device_id)} pending={pending[emulator.device_id]} onOperate={action => void operate(emulator, action)} onLaunch={() => { const device = emulatorConnectionDevice(emulator, devices); if (device) { setSelected(null); onLaunch(device); } }} />;
  return <section className="managed-emulators" aria-labelledby="managed-emulator-heading">
    <div className="section-heading"><div><h2 id="managed-emulator-heading">{t("Émulateurs gérés")}</h2><p>{t("Allumez Android, préparez ses applications, puis lancez vos parcours.")}</p></div><div className="row-actions"><button type="button" className="text-button" onClick={() => void load()}><Icon name="refresh" size={16} />{t("Actualiser")}</button>{canManage && <button type="button" className="button button--primary" disabled={!catalog?.enabled || !catalog.hosts.length} onClick={() => setCreating(true)}><Icon name="plus" size={18} />{t("Créer un émulateur")}</button>}</div></div>
    {error && <ErrorNotice message={error} />}
    {!catalog ? <div className="surface emulator-loading" role="status">{t(error ? "La liste des émulateurs est indisponible. Réessayez." : "Chargement des émulateurs…")}</div> : <>
      {(!catalog.enabled || !catalog.hosts.length) && <p className="notice notice--warning">{t("Aucun hôte n’est disponible pour gérer un émulateur.")}</p>}
      {!catalog.items.length ? <div className="surface emulator-empty"><Icon name="phone" size={28} /><h3>{t("Votre premier émulateur")}</h3><p>{t("Créez un environnement Android avec les applications dont vos parcours ont besoin.")}</p></div> : <div className="emulator-grid tw:grid tw:grid-cols-1 tw:gap-4 tw:min-[760px]:grid-cols-2 tw:min-[1500px]:grid-cols-3">{catalog.items.map(emulator => <article className="surface emulator-card" key={emulator.device_id}><div className="emulator-card-heading"><h3>{emulator.display_name}</h3><EmulatorState emulator={emulator} /></div><p className="emulator-host"><Icon name="phone" size={15} /><bdi>{emulator.host_id}</bdi><span aria-hidden="true">·</span><bdi>{emulatorPlatform}</bdi></p><EmulatorOperationStatus emulator={emulator} /><div className="emulator-app-chips">{emulator.application_ids.length ? emulator.application_ids.map(id => <span key={id}>{catalog.applications.find(application => application.id === id)?.name ?? t("Application inconnue")}</span>) : <span>{t("Aucune application sélectionnée")}</span>}</div>{emulatorOperationActive(emulator) && <p className="small-copy" role="status">{t("Opération en cours. La disponibilité sera vérifiée à la fin.")}</p>}{emulator.last_error && <p className="execution-error">{emulator.last_error}</p>}{operationErrors[emulator.device_id] && <ErrorNotice message={operationErrors[emulator.device_id]} />}{actions(emulator)}<div className="emulator-card-links"><button type="button" className="text-button" onClick={() => setSelected(emulator.device_id)}>{t("Applications et détails")}</button>{emulator.last_run_id && <button type="button" className="text-button" onClick={() => onOpenRun(emulator.last_run_id!)}>{t("Voir la dernière opération")}<Icon name="arrow" size={15} /></button>}</div></article>)}</div>}
      {creating && <EmulatorForm userId={userId} catalog={catalog} onClose={() => setCreating(false)} onUploaded={uploaded} onCreated={emulator => { setCreating(false); setSelected(emulator.device_id); changed(emulator); }} />}
      {current && <EmulatorDetails key={current.device_id} emulator={current} catalog={catalog} canManage={canManage} sending={sending.includes(current.device_id)} pending={!!pending[current.device_id]} operationError={operationErrors[current.device_id]} onClose={() => setSelected(null)} onUploaded={uploaded} onSaved={changed} actions={actions(current)} onOpenRun={() => { setSelected(null); if (current.last_run_id) onOpenRun(current.last_run_id); }} />}
    </>}
  </section>;
}

function EmulatorState({ emulator }: { emulator: ManagedEmulator }) {
  const { t } = useLocale();
  const active = emulatorOperationActive(emulator);
  const label = emulator.operation_status === "queued" ? "En attente" : active && !["starting", "preparing"].includes(emulator.state) ? "En cours" : labels[emulator.state];
  return <span className={`status-badge status-badge--${active ? "amber" : emulator.state === "ready" ? "green" : emulator.state === "running" ? "blue" : emulator.state === "failed" ? "red" : emulator.state === "stopped" || emulator.state === "created" ? "neutral" : "amber"}`}><span className="status-dot" />{t(label)}</span>;
}

function EmulatorOperationStatus({ emulator }: { emulator: ManagedEmulator }) {
  const { t } = useLocale();
  return emulator.operation_status ? <div className="emulator-operation-status"><span>{t("Dernière opération")}</span><Badge status={emulator.operation_status} /></div> : null;
}

function EmulatorActions({ emulator, applications, canManage, canLaunch, ready, sending, pending, onOperate, onLaunch }: { emulator: ManagedEmulator; applications: EmulatorApplication[]; canManage: boolean; canLaunch: boolean; ready: boolean; sending: boolean; pending?: EmulatorOperation; onOperate: (action: EmulatorAction) => void; onLaunch: () => void }) {
  const { t } = useLocale(), missing = missingEmulatorApplications(emulator.application_ids, applications).length > 0;
  return <div className="emulator-actions">
    {canManage && (pending ? <><p className="small-copy">{t("La demande précédente est conservée. Réessayez pour confirmer son résultat.")}</p><button type="button" className="button button--secondary" disabled={sending} onClick={() => onOperate(pending.action)}>{t(sending ? "Demande en cours…" : "Confirmer le résultat de la demande")}</button></> : <div className="emulator-management-controls"><div className="emulator-power-controls"><button type="button" className="button button--secondary" disabled={sending || !emulatorCanManage(emulator, "start", applications)} onClick={() => onOperate("start")}><Icon name="play" size={16} />{t("Allumer")}</button><button type="button" className="button button--secondary" disabled={sending || !emulatorCanManage(emulator, "stop", applications)} onClick={() => onOperate("stop")}><Icon name="power" size={16} />{t("Éteindre")}</button></div><button type="button" className="button button--secondary emulator-prepare-button" disabled={sending || !emulatorCanManage(emulator, "prepare", applications)} onClick={() => onOperate("prepare")}><Icon name="refresh" size={16} />{t("Préparer les applications")}</button><p className="emulator-action-note">{t("La préparation allume Android si nécessaire et installe les applications choisies.")}</p></div>)}
    {missing && <p className="emulator-action-note">{t("Importez les APK manquants pour préparer cet émulateur.")}</p>}
    {emulator.availability !== "declared" && <p className="emulator-action-note">{t(emulator.availability === "needs_review" ? "Cet appareil nécessite une vérification avant toute nouvelle opération." : "L’appareil est réservé. Attendez la fin de l’exécution avant de le modifier.")}</p>}
    {canLaunch && <button type="button" className="button button--primary" disabled={!ready || sending || !!pending} onClick={onLaunch}><Icon name="play" size={16} />{t("Lancer un parcours")}</button>}
    {canLaunch && emulator.state === "ready" && !ready && <p className="emulator-action-note">{t("La connexion Android doit être confirmée avant le lancement.")}</p>}
  </div>;
}

function ApplicationPicker({ applications, selected, onChange, disabled, onUploaded, onUploading }: { applications: EmulatorApplication[]; selected: string[]; onChange: (ids: string[]) => void; disabled: boolean; onUploaded: (application: EmulatorApplication) => void; onUploading: (busy: boolean) => void }) {
  const { t, locale } = useLocale(), fileInput = useRef<HTMLInputElement>(null);
  const [importSource, setImportSource] = useState<"file" | "fdroid" | null>(null);
  const [error, setError] = useState(""), [imported, setImported] = useState("");
  const uploading = importSource !== null;
  const canSelectPackage = (packageName: string) => selected.length < 12 ||
    applications.some(application => application.package_name === packageName && selected.includes(application.id));

  async function upload(file: File | undefined) {
    if (!file || uploading || disabled) return;
    setError("");
    setImported("");
    if (!file.name.toLowerCase().endsWith(".apk") || file.size === 0 || file.size > MAX_APK_BYTES) { setError(t("Choisissez un fichier APK de moins de 128 Mio.")); if (fileInput.current) fileInput.current.value = ""; return; }
    setImportSource("file"); onUploading(true);
    try {
      const body = new FormData(); body.append("file", file);
      const response = await fetch("/api/control/console/applications", { method: "POST", credentials: "same-origin", cache: "no-store", headers: { "X-Emulytix-Client": "console" }, body });
      if (response.status === 401) { window.location.assign("/connexion"); return; }
      if (!response.ok) throw new ApiError(response.status, t(response.status === 413 ? "Choisissez un fichier APK de moins de 128 Mio." : "L’importation a échoué. Vérifiez le fichier APK puis réessayez."));
      const uploaded = await response.json() as EmulatorApplication;
      const result = canonicalizeEmulatorUpload(uploaded, applications, selected);
      onUploaded(result.application); onChange(result.selected);
    } catch (failure) { setError(failure instanceof ApiError ? failure.message : t("L’importation a échoué. Vérifiez le fichier APK puis réessayez.")); }
    finally { setImportSource(null); onUploading(false); if (fileInput.current) fileInput.current.value = ""; }
  }

  async function importRelease(packageName: string, sha256: string) {
    if (uploading || disabled || !canSelectPackage(packageName)) return;
    setImportSource("fdroid"); onUploading(true); setError(""); setImported("");
    try {
      const application = await api<EmulatorApplication>("console/applications/fdroid", { package_name: packageName, sha256 });
      onUploaded(application);
      onChange(selectEmulatorApplication(application, applications, selected));
      setImported(application.name);
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 404
        ? t("Cette version n’est plus disponible. Relancez la recherche.")
        : t("L’importation depuis F-Droid a échoué. Réessayez."));
    } finally {
      setImportSource(null); onUploading(false);
    }
  }
  const size = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });
  return <div className="emulator-application-picker">
    <fieldset disabled={disabled || uploading}>
      <legend>{t("Applications souhaitées")}</legend>
      <p className="small-copy">{t("Sélectionnez jusqu’à {count} applications.", { count: 12 })}</p>
      <div className="emulator-application-options">{applications.map(application => {
        const checked = selected.includes(application.id);
        return <label className="emulator-app-option" key={application.id}>
          <input type="checkbox" checked={checked} disabled={!checked && !canSelectPackage(application.package_name)}
            onChange={() => onChange(checked ? selected.filter(id => id !== application.id) : selectEmulatorApplication(application, applications, selected))} />
          <span><strong>{application.name}</strong><small className={!application.available ? "emulator-apk-missing" : undefined}>
            {t(application.source === "system" ? "Application fournie avec Android" : application.available ? "APK disponible" : "APK à importer")}
            {application.source === "apk" && application.available && application.size_bytes > 0 && ` · ${t("{n} Mio", { n: size.format(application.size_bytes / 1048576) })}`}
          </small></span>
        </label>;
      })}</div>
    </fieldset>
    {!disabled && <>
      <FDroidPicker busy={uploading} importing={importSource === "fdroid"} canSelectPackage={canSelectPackage}
        onImport={(packageName, sha256) => void importRelease(packageName, sha256)} />
      {imported && <p className="small-copy" role="status">{t("{name} a été ajouté à la sélection.", { name: imported })}</p>}
      {error && <ErrorNotice message={error} />}
      <input ref={fileInput} className="sr-only" type="file" accept=".apk,application/vnd.android.package-archive" tabIndex={-1} aria-hidden="true" onChange={event => void upload(event.target.files?.[0])} />
      <button type="button" className="button button--secondary" disabled={uploading} onClick={() => fileInput.current?.click()}>
        <Icon name="plus" size={16} />{t(importSource === "file" ? "Importation en cours…" : "Importer un APK")}
      </button>
      <p className="small-copy">{t("L’application est reconnue automatiquement. Importez un APK compatible avec la version Android et l’architecture de l’émulateur.")}</p>
    </>}
  </div>;
}

function EmulatorForm({ userId, catalog, onClose, onUploaded, onCreated }: { userId: string; catalog: EmulatorCatalog; onClose: () => void; onUploaded: (application: EmulatorApplication) => void; onCreated: (emulator: ManagedEmulator) => void }) {
  const { t, locale } = useLocale();
  const [name, setName] = useState(""), [host, setHost] = useState(catalog.hosts.length === 1 ? catalog.hosts[0] : ""), [selected, setSelected] = useState<string[]>([]);
  const [hardware, setHardware] = useState<EmulatorHardware>({ ...DEFAULT_HARDWARE });
  const [busy, setBusy] = useState(false), [uploading, setUploading] = useState(false), [error, setError] = useState(""), [attempted, setAttempted] = useState(false);
  const intent = useRef<EmulatorCreation | null>(null), sending = useRef(false);
  useEffect(() => { try { const raw = sessionStorage.getItem(emulatorIntentKey(userId)); const saved = raw ? parseEmulatorCreation(JSON.parse(raw)) : null; if (saved) { intent.current = saved; setName(saved.name); setHost(saved.host_id); setSelected(saved.application_ids); setHardware(saved.hardware ?? { ...DEFAULT_HARDWARE }); setAttempted(true); } } catch { setError(t(storageError)); } }, [userId, t]);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (sending.current || uploading) return;
    if (!intent.current && !parseHardware(hardware)) { setError(hardwareCopy[locale].bounds); return; }
    sending.current = true; setBusy(true); setError(""); let sent = false;
    const request = intent.current ?? { name: name.trim(), host_id: host, application_ids: selected, hardware, idempotency_key: crypto.randomUUID() };
    try {
      sessionStorage.setItem(emulatorIntentKey(userId), JSON.stringify(request)); intent.current = request; setAttempted(true); sent = true;
      const emulator = await api<ManagedEmulator>("console/emulators", request);
      sessionStorage.removeItem(emulatorIntentKey(userId)); intent.current = null; onCreated(emulator);
    } catch (failure) {
      if (!sent || definite(failure)) { try { sessionStorage.removeItem(emulatorIntentKey(userId)); } catch {} intent.current = null; setAttempted(false); }
      setError(!sent ? t(storageError) : failure instanceof ApiError ? failure.message : t("Le service est indisponible. Réessayez dans un instant."));
    } finally { sending.current = false; setBusy(false); }
  }
  return <Dialog title={t("Créer un émulateur")} description={t("Choisissez ses applications maintenant, puis utilisez « Préparer les applications » pour les installer.")} onClose={() => { if (!busy && !uploading) onClose(); }} wide><form className="dialog-form emulator-form" onSubmit={submit}>
    {error && <ErrorNotice message={error} />}{attempted && <p className="notice notice--warning">{t("La demande précédente est conservée. Réessayez pour confirmer son résultat.")}</p>}
    <fieldset className="emulator-form-fields" disabled={busy || attempted || uploading}><label>{t("Nom de l’émulateur")}<input required maxLength={160} autoFocus value={name} onChange={event => setName(event.target.value)} placeholder={t("Ex. Android marketing")} /><span>{t("Les espaces sont acceptés. L’identifiant est généré automatiquement.")}</span></label><label>{t("Hôte de l’émulateur")}<select required value={host} onChange={event => setHost(event.target.value)}><option value="" disabled>{t("Choisir un hôte")}</option>{![...catalog.hosts].includes(host) && host && <option value={host}>{host}</option>}{catalog.hosts.map(value => <option key={value} value={value}>{value}</option>)}</select><span>{t("Jusqu’à {count} émulateurs par hôte.", { count: catalog.max_per_host })}</span></label></fieldset>
    <p className="emulator-platform"><bdi>{emulatorPlatform}</bdi></p><EmulatorHardwareFields value={hardware} onChange={setHardware} disabled={busy || attempted || uploading} /><ApplicationPicker applications={catalog.applications} selected={selected} onChange={setSelected} disabled={busy || attempted} onUploaded={onUploaded} onUploading={setUploading} />
    {missingEmulatorApplications(selected, catalog.applications).length > 0 && <p className="notice notice--info">{t("Vous pouvez enregistrer ce choix maintenant et importer les APK avant de préparer l’émulateur.")}</p>}
    <div className="dialog-footer"><button type="button" className="button button--secondary" disabled={busy || uploading} onClick={onClose}>{t("Annuler")}</button><button type="submit" className="button button--primary" disabled={busy || uploading || !attempted && (!name.trim() || !host)}>{t(busy ? "Création en cours…" : attempted ? "Confirmer le résultat de la demande" : "Créer l’émulateur")}</button></div>
  </form></Dialog>;
}

function EmulatorDetails({ emulator, catalog, canManage, sending, pending, operationError, onClose, onUploaded, onSaved, actions, onOpenRun }: { emulator: ManagedEmulator; catalog: EmulatorCatalog; canManage: boolean; sending: boolean; pending: boolean; operationError?: string; onClose: () => void; onUploaded: (application: EmulatorApplication) => void; onSaved: (emulator: ManagedEmulator) => void; actions: ReactNode; onOpenRun: () => void }) {
  const { t, locale } = useLocale();
  const [selected, setSelected] = useState(emulator.application_ids), [busy, setBusy] = useState(false), [uploading, setUploading] = useState(false), [error, setError] = useState("");
  const [hardware, setHardware] = useState<EmulatorHardware>(emulator.hardware ?? { ...DEFAULT_HARDWARE });
  const copy = hardwareCopy[locale];
  const editable = canManage && catalog.enabled && emulator.availability === "declared" && !emulatorOperationActive(emulator) && !sending && !pending;
  const canEditHardware = editable && hardwareEditable(emulator);
  const hardwareDirty = !sameHardware(hardware, emulator.hardware ?? DEFAULT_HARDWARE);
  const dirty = hardwareDirty || [...selected].sort().join("\0") !== [...emulator.application_ids].sort().join("\0");
  async function save(event: FormEvent) {
    event.preventDefault(); if (!editable || busy || uploading) return; setBusy(true); setError("");
    if (hardwareDirty && !canEditHardware || !parseHardware(hardware)) { setError(hardwareDirty && !canEditHardware ? copy.stop : copy.bounds); setBusy(false); return; }
    try { const result = await api<ManagedEmulator>(`console/emulators/${encodeURIComponent(emulator.device_id)}/configuration`, { application_ids: selected, ...(hardwareDirty ? { hardware } : {}) }); setSelected(result.application_ids); setHardware(result.hardware ?? { ...DEFAULT_HARDWARE }); onSaved(result); }
    catch (failure) { setError((failure as Error).message); } finally { setBusy(false); }
  }
  return <Dialog title={emulator.display_name} description={t("Applications et préparation de l’émulateur.")} onClose={() => { if (!busy && !uploading) onClose(); }} wide><div className="dialog-form emulator-details">
    <p className="emulator-host"><bdi>{emulator.host_id}</bdi><span aria-hidden="true">·</span><bdi>{emulatorPlatform}</bdi></p><EmulatorOperationStatus emulator={emulator} /><div className="emulator-detail-status"><EmulatorState emulator={emulator} /><Badge status={emulator.availability} /><span>{t("Mis à jour à {time}", { time: date(emulator.updated_at, locale) })}</span></div>
    {(error || operationError) && <ErrorNotice message={error || operationError!} />}{emulator.last_error && <ErrorNotice message={emulator.last_error} />}
    <form className="emulator-config-form" onSubmit={save}>
      <EmulatorHardwareFields value={canManage ? hardware : emulator.hardware ?? DEFAULT_HARDWARE} onChange={setHardware} disabled={!canEditHardware || busy || uploading} storageEditable={emulator.storage_editable === true} />
      {canManage && !hardwareEditable(emulator) && <p className="small-copy">{copy.stop}</p>}
      <div className="emulator-applied-hardware"><strong>{copy.applied}</strong><p className="small-copy">{emulator.applied_hardware ? <HardwareSummary hardware={emulator.applied_hardware} applied /> : copy.notApplied}</p><p className="small-copy">{hardwareStorageCopy[locale].flags}</p>{emulator.applied_hardware && !sameAppliedHardware(emulator.hardware ?? DEFAULT_HARDWARE, emulator.applied_hardware) && <p className="notice notice--info">{copy.pending}</p>}</div>
      <ApplicationPicker applications={catalog.applications} selected={canManage ? selected : emulator.application_ids} onChange={setSelected} disabled={!editable || busy} onUploaded={onUploaded} onUploading={setUploading} />{canManage && <button type="submit" className="button button--secondary" disabled={!editable || busy || uploading || !dirty || hardwareDirty && !canEditHardware}>{busy ? t("Enregistrement…") : copy.save}</button>}
    </form>
    <section className="emulator-installed"><h3>{t("Applications détectées")}</h3>{emulator.installed_packages.length ? <ul>{emulator.installed_packages.map(value => <li key={value}>{catalog.applications.find(application => application.package_name === value)?.name ?? value}</li>)}</ul> : <p className="small-copy">{t("Aucune vérification d’application n’a encore été enregistrée.")}</p>}</section>
    <fieldset className="emulator-action-fieldset" disabled={dirty || busy || uploading}>{actions}</fieldset>
    {emulator.last_run_id && <button type="button" className="text-button" onClick={onOpenRun}>{t("Voir la dernière opération")}<Icon name="arrow" size={16} /></button>}
    <div className="dialog-footer"><button type="button" className="button button--secondary" disabled={busy || uploading} onClick={onClose}>{t("Fermer")}</button></div>
  </div></Dialog>;
}
