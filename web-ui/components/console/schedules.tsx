"use client";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError } from "../../lib/client-api";
import { useLocale, useT } from "../../lib/i18n";
import type { Device, Page, Schedule, Workflow } from "../../lib/console-types";
import { Dialog, Empty, ErrorNotice, date, workflowName } from "./shared";
import { Icon } from "./icons";
import { parseScheduleDraft, scheduleDraftKey, type ScheduleSubmission } from "../../lib/schedule-draft";

export function Schedules({
  userId,
  devices,
  workflows,
  canWrite,
  initial,
  onInitialUsed,
  onOpenRun,
}: {
  userId: string;
  devices: Device[];
  workflows: Workflow[];
  canWrite: boolean;
  initial?: Workflow | null;
  onInitialUsed: () => void;
  onOpenRun: (id: string) => void;
}) {
  const t = useT(),
    { locale } = useLocale();
  const [items, setItems] = useState<Schedule[]>([]),
    [total, setTotal] = useState(0),
    [offset, setOffset] = useState(0),
    [error, setError] = useState(""),
    [adding, setAdding] = useState(false),
    [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      const result = await api<Page<Schedule>>(
        `console/schedules?limit=50&offset=${offset}`,
      );
      setItems(result.items);
      setTotal(result.total ?? result.items.length);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, [offset]);
  useEffect(() => {
    void load();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, 10000);
    return () => clearInterval(timer);
  }, [load]);
  useEffect(() => {
    if (initial) setAdding(true);
  }, [initial]);
  async function toggle(item: Schedule) {
    setBusy(true);
    try {
      await api(
        `console/schedules/${item.id}`,
        { enabled: !item.enabled },
        "PATCH",
      );
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="section-heading">
        <div>
          <h2>{t("Planifications")}</h2>
          <p>
            {t("Choisissez quand lancer un parcours et sur quels appareils.")}
          </p>
        </div>
        {canWrite && (
          <button
            className="button button--primary"
            onClick={() => setAdding(true)}
          >
            <Icon name="plus" />
            {t("Nouvelle planification")}
          </button>
        )}
      </div>
      {error && <ErrorNotice message={error} />}
      {!items.length ? (
        <section className="surface">
          <Empty icon="workflow" title={t("Aucune planification")}>
            {t(
              "Planifiez une version publiée pour automatiser vos lancements.",
            )}
          </Empty>
        </section>
      ) : (
        <section className="surface schedule-list">
          {items.map((item) => (
            <article className="recipe-row" key={item.id}>
              <div>
                <h3>{item.name}</h3>
                <p>
                  {t(workflowName(item.workflow_id))} · v{item.workflow_version}{" "}
                  · {t("{n} appareils", { n: item.device_ids.length })}
                </p>
                <div className="metadata-line">
                  <code dir="ltr">{item.cron}</code>
                  <span dir="ltr">{item.timezone}</span>
                  <span>{t(item.enabled ? "Active" : "En pause")}</span>
                </div>
                <p>
                  {t("Prochain lancement")} :{" "}
                  {item.enabled && item.next_run_at
                    ? date(item.next_run_at, locale, item.timezone)
                    : "—"}
                </p>
                {item.last_error && (
                  <div className="notice notice--error">
                    {t(
                      "Le dernier déclenchement a échoué. Vérifiez les droits du créateur et la disponibilité des appareils.",
                    )}
                  </div>
                )}
                {item.last_run_id && (
                  <button
                    className="text-button"
                    onClick={() => onOpenRun(item.last_run_id!)}
                  >
                    {t("Voir la dernière exécution")}
                  </button>
                )}
              </div>
              {canWrite && (
                <button
                  className="button button--secondary"
                  disabled={busy}
                  onClick={() => void toggle(item)}
                >
                  {t(item.enabled ? "Mettre en pause" : "Reprendre")}
                </button>
              )}
            </article>
          ))}
        </section>
      )}
      <div className="table-footer">
        <span>{t("{n} planifications", { n: total })}</span>
        <div className="row-actions">
          <button
            className="button button--secondary"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - 50))}
          >
            {t("Précédent")}
          </button>
          <button
            className="button button--secondary"
            disabled={offset + 50 >= total}
            onClick={() => setOffset(offset + 50)}
          >
            {t("Suivant")}
          </button>
        </div>
      </div>
      {adding && (
        <ScheduleEditor
          userId={userId}
          devices={devices}
          workflows={workflows}
          initial={initial}
          onClose={() => {
            setAdding(false);
            onInitialUsed();
          }}
          onSaved={() => {
            setAdding(false);
            onInitialUsed();
            void load();
          }}
        />
      )}
    </>
  );
}
export function ScheduleEditor({
  userId,
  devices,
  workflows,
  initial,
  onClose,
  onSaved,
}: {
  userId: string;
  devices: Device[];
  workflows: Workflow[];
  initial?: Workflow | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useT(),
    { locale } = useLocale();
  const [key, setKey] = useState(
      initial ? `${initial.workflow_id}:${initial.version}` : "",
    ),
    [name, setName] = useState(""),
    [selected, setSelected] = useState<string[]>([]),
    [concurrency, setConcurrency] = useState(1),
    [mode, setMode] = useState("daily"),
    [time, setTime] = useState("09:00"),
    [weekday, setWeekday] = useState("1"),
    [monthday, setMonthday] = useState("1"),
    [zone, setZone] = useState("Europe/Paris"),
    [raw, setRaw] = useState("0 9 * * *"),
    [next, setNext] = useState<string[]>([]),
    [previewZone, setPreviewZone] = useState("Europe/Paris"),
    [previewError, setPreviewError] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [attempted, setAttempted] = useState(false);
  const intent = useRef<ScheduleSubmission | null>(null), sending = useRef(false);
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(scheduleDraftKey(userId));
      const pending = raw ? parseScheduleDraft(JSON.parse(raw)) : null;
      if (pending) {
        intent.current = pending; setAttempted(true); setName(pending.name);
        setKey(`${pending.workflow_id}:${pending.workflow_version}`); setSelected(pending.device_ids);
        setConcurrency(pending.max_concurrency); setMode("advanced"); setRaw(pending.cron); setZone(pending.timezone);
      }
    } catch { setError(t("Autorisez le stockage de session du navigateur pour sécuriser cette demande.")); }
  }, [userId, t]);
  const [h, m] = time.split(":").map(Number);
  const cron =
    mode === "advanced"
      ? raw.trim().replace(/\s+/g, " ")
      : `${m} ${h} ${mode === "monthly" ? monthday : "*"} * ${mode === "weekly" ? weekday : "*"}`;
  useEffect(() => {
    let cancelled = false;
    setNext([]);
    const timer = setTimeout(() => {
      void api<{ next_runs: string[] }>("console/schedules/preview", {
        cron,
        timezone: zone.trim(),
      })
        .then((result) => {
          if (!cancelled) {
            setNext(result.next_runs);
            setPreviewZone(zone.trim());
            setPreviewError("");
          }
        })
        .catch(() => {
          if (!cancelled)
            setPreviewError(
              t("Vérifiez l’expression CRON et le fuseau horaire."),
            );
        });
    }, 350);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [cron, zone, t]);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (sending.current) return;
    const workflow = workflows.find((w) => `${w.workflow_id}:${w.version}` === key);
    const request = intent.current ?? (workflow ? parseScheduleDraft({
      request_id: crypto.randomUUID(), name: name.trim(), workflow_id: workflow.workflow_id,
      workflow_version: workflow.version, device_ids: selected, max_concurrency: Math.min(selected.length, concurrency),
      cron, timezone: zone.trim(), enabled: true,
    }) : null);
    if (!request) { setError(t("Vérifiez les informations saisies.")); return; }
    sending.current = true; setBusy(true);
    setError("");
    let sent = false;
    try {
      sessionStorage.setItem(scheduleDraftKey(userId), JSON.stringify(request));
      intent.current = request; setAttempted(true); sent = true;
      await api("console/schedules", request);
      try { sessionStorage.removeItem(scheduleDraftKey(userId)); } catch { /* Replaying a confirmed request is safe. */ }
      intent.current = null;
      onSaved();
    } catch (failure) {
      if (!sent || failure instanceof ApiError && [401, 403, 404, 409, 422].includes(failure.status)) {
        try { sessionStorage.removeItem(scheduleDraftKey(userId)); } catch {}
        intent.current = null; setAttempted(false);
      }
      setError(!sent ? t("Autorisez le stockage de session du navigateur pour sécuriser cette demande.") : (failure as Error).message);
    } finally {
      sending.current = false; setBusy(false);
    }
  }
  return (
    <Dialog
      wide
      title={t("Nouvelle planification")}
      description={t(
        "Le fuseau horaire est conservé avec cette planification.",
      )}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="dialog-form" onSubmit={submit}>
        {error && <ErrorNotice message={error} />}
        {attempted && <p className="notice notice--warning">{t("La demande précédente est conservée. Réessayez pour confirmer son résultat.")}</p>}
        <fieldset className="schedule-editor-fields" disabled={busy || attempted}>
        <label>
          {t("Nom de la planification")}
          <input
            name="name"
            required
            maxLength={120}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("Ex. Vérification du matin")}
          />
        </label>
        <label>
          {t("Parcours publié")}
          <select required value={key} onChange={(e) => setKey(e.target.value)}>
            <option value="">{t("Choisir un parcours")}</option>
            {intent.current && !workflows.some(w => `${w.workflow_id}:${w.version}` === key) && <option value={key}>{intent.current.workflow_id} · v{intent.current.workflow_version}</option>}
            {workflows.map((w) => (
              <option
                key={`${w.workflow_id}:${w.version}`}
                value={`${w.workflow_id}:${w.version}`}
              >
                {w.name || t(workflowName(w.workflow_id))} · v{w.version}
              </option>
            ))}
          </select>
        </label>
        <fieldset className="device-picker">
          <legend>{t("Appareils ciblés")}</legend>
          {devices.length ? (
            devices.map((d) => (
              <label className="checkbox-label" key={d.device_id}>
                <input
                  type="checkbox"
                  disabled={
                    d.availability === "needs_review" ||
                    (!selected.includes(d.device_id) && selected.length >= 100)
                  }
                  checked={selected.includes(d.device_id)}
                  onChange={(e) =>
                    setSelected((ids) =>
                      e.target.checked
                        ? [...ids, d.device_id]
                        : ids.filter((id) => id !== d.device_id),
                    )
                  }
                />
                <span>
                  {d.display_name || d.device_id}
                  {d.availability === "needs_review"
                    ? ` · ${t("À vérifier")}`
                    : ""}
                </span>
              </label>
            ))
          ) : (
            <p>{t("Ajoutez un appareil avant de planifier un parcours.")}</p>
          )}
        </fieldset>
        <div className="form-grid">
          <label>
            {t("Fréquence")}
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="daily">{t("Chaque jour")}</option>
              <option value="weekly">{t("Chaque semaine")}</option>
              <option value="monthly">{t("Chaque mois")}</option>
              <option value="advanced">{t("CRON avancé")}</option>
            </select>
          </label>
          {mode !== "advanced" && (
            <label>
              {t("Heure locale")}
              <input
                type="time"
                required
                value={time}
                onChange={(e) => setTime(e.target.value)}
              />
            </label>
          )}
        </div>
        {mode === "weekly" && (
          <label>
            {t("Jour de la semaine")}
            <select
              value={weekday}
              onChange={(e) => setWeekday(e.target.value)}
            >
              {[
                "Dimanche",
                "Lundi",
                "Mardi",
                "Mercredi",
                "Jeudi",
                "Vendredi",
                "Samedi",
              ].map((d, i) => (
                <option value={i} key={d}>
                  {t(d)}
                </option>
              ))}
            </select>
          </label>
        )}
        {mode === "monthly" && (
          <label>
            {t("Jour du mois")}
            <select
              value={monthday}
              onChange={(e) => setMonthday(e.target.value)}
            >
              {Array.from({ length: 28 }, (_, i) => (
                <option key={i + 1} value={i + 1}>
                  {i + 1}
                </option>
              ))}
            </select>
            <span>{t("Les jours 1 à 28 existent dans tous les mois.")}</span>
          </label>
        )}
        {mode === "advanced" && (
          <label>
            {t("Expression CRON")}
            <input
              required
              dir="ltr"
              value={raw}
              onChange={(e) => setRaw(e.target.value)}
              placeholder="0 9 * * 1-5"
            />
            <span>
              {t("Minute · heure · jour du mois · mois · jour de semaine")}
            </span>
          </label>
        )}
        <label>
          {t("Fuseau horaire")}
          <input
            required
            list="timezones"
            dir="ltr"
            value={zone}
            onChange={(e) => setZone(e.target.value)}
          />
          <datalist id="timezones">
            {[
              "Europe/Paris",
              "Europe/London",
              "America/New_York",
              "America/Sao_Paulo",
              "Asia/Shanghai",
              "Asia/Kolkata",
              "Asia/Dhaka",
              "Asia/Dubai",
              "Europe/Moscow",
              "UTC",
            ].map((z) => (
              <option key={z} value={z} />
            ))}
          </datalist>
        </label>
        <label>
          {t("Exécutions simultanées")}
          <input
            name="max_concurrency"
            type="number"
            required
            value={concurrency}
            onChange={(e) => setConcurrency(Number(e.target.value))}
            min={1}
            max={Math.max(1, selected.length)}
          />
        </label>
        <section className="schedule-preview" aria-live="polite">
          <h3>{t("Prochains lancements")}</h3>
          {previewError ? (
            <p>{previewError}</p>
          ) : next.length ? (
            <ol>
              {next.slice(0, 5).map((n) => (
                <li key={n}>
                  {new Intl.DateTimeFormat(locale, {
                    dateStyle: "medium",
                    timeStyle: "short",
                    timeZone: previewZone,
                  }).format(new Date(n))}
                </li>
              ))}
            </ol>
          ) : (
            <p>{t("Calcul des prochaines dates…")}</p>
          )}
          <code dir="ltr">{cron}</code>
          <p>
            {t(
              "Une échéance interrompue est reprise sans créer de doublon. Les échéances manquées ne sont pas relancées en rafale.",
            )}
          </p>
        </section>
        </fieldset>
        <div className="dialog-footer">
          <button
            type="button"
            className="button button--secondary"
            disabled={busy}
            onClick={onClose}
          >
            {t("Annuler")}
          </button>
          <button
            className="button button--primary"
            disabled={
              busy || !attempted && (!selected.length || !next.length || !!previewError)
            }
          >
            {t(busy ? "Enregistrement…" : attempted ? "Confirmer le résultat de la demande" : "Créer la planification")}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
