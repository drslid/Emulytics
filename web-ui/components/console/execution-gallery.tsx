"use client";

import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import type { Execution, Step } from "../../lib/console-types";
import { buildExecutionGallery, initialGallerySelection, type GalleryState, type GalleryStep } from "../../lib/execution-gallery";
import { useLocale } from "../../lib/i18n";
import { editorActions } from "../../lib/workflow-editor";
import { Icon } from "./icons";

const states: Record<GalleryState, { label: string; tone: string; icon: "clock" | "check" | "warning" | "close" }> = {
  pending: { label: "En attente", tone: "neutral", icon: "clock" },
  succeeded: { label: "Réussie", tone: "green", icon: "check" },
  skipped: { label: "Ignorée", tone: "neutral", icon: "close" },
  failed: { label: "Échouée", tone: "red", icon: "warning" },
  "not-run": { label: "Non exécutée", tone: "neutral", icon: "close" },
  unconfirmed: { label: "Non confirmée", tone: "amber", icon: "warning" },
};
type Capture = { key: string; status: "loading" | "ready" | "error" | "forbidden" | "missing" | "expired"; url?: string };

function useCapture(source: string | null, key: string, retry: number): Capture | null {
  const [capture, setCapture] = useState<Capture | null>(null);
  useEffect(() => {
    if (!source) { setCapture(null); return; }
    const controller = new AbortController();
    let stopped = false;
    let objectUrl: string | null = null;
    const timeout = setTimeout(() => controller.abort(), 15_000);
    setCapture({ key, status: "loading" });
    async function load() {
      try {
        const response = await fetch(source!, { credentials: "same-origin", cache: "no-store", signal: controller.signal, headers: { Accept: "image/png" } });
        if (stopped) return;
        if (response.status === 401 || response.status === 403 || response.status === 404) {
          setCapture({ key, status: response.status === 401 ? "expired" : response.status === 403 ? "forbidden" : "missing" });
          if (response.status === 401) window.location.assign("/connexion");
          return;
        }
        if (!response.ok || response.headers.get("content-type")?.split(";")[0].trim() !== "image/png") throw new Error("Invalid capture response");
        const blob = await response.blob();
        if (stopped) return;
        if (blob.size < 8 || blob.size > 16 * 1024 * 1024) throw new Error("Invalid capture size");
        objectUrl = URL.createObjectURL(blob);
        const image = new Image();
        image.src = objectUrl;
        await image.decode();
        if (!stopped) setCapture({ key, status: "ready", url: objectUrl });
      } catch {
        if (!stopped) {
          if (objectUrl) URL.revokeObjectURL(objectUrl);
          objectUrl = null;
          setCapture({ key, status: "error" });
        }
      } finally { clearTimeout(timeout); }
    }
    void load();
    return () => { stopped = true; clearTimeout(timeout); controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [source, key, retry]);
  return source ? capture?.key === key ? capture : { key, status: "loading" } : null;
}

function StepState({ state }: { state: GalleryState }) {
  const { t } = useLocale();
  const item = states[state];
  return <span className={`status-badge status-badge--${item.tone} execution-step-state`}><Icon name={item.icon} size={12} />{t(item.label)}</span>;
}

function Thumbnail({ step, blocked, retry }: { step: GalleryStep; blocked: boolean; retry: number }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [step.captureUrl, retry]);
  return <span className="execution-step-thumbnail" aria-hidden="true">
    {step.captureUrl && !failed && !blocked ? <img src={step.captureUrl} alt="" loading="lazy" decoding="async" onError={() => setFailed(true)} /> : <Icon name={step.captureUrl ? "warning" : "phone"} size={22} />}
  </span>;
}

export function ExecutionGallery({ execution, steps, compact = false }: { execution: Execution; steps?: Step[]; compact?: boolean }) {
  const { t, locale } = useLocale();
  const titleId = useId();
  const previewId = useId();
  const rows = useMemo(() => buildExecutionGallery(execution, steps), [execution, steps]);
  const [selection, setSelection] = useState<{ executionId: string; id: string } | null>(null);
  const [retry, setRetry] = useState(0);
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const selectedId = initialGallerySelection(rows, selection?.executionId === execution.id ? selection.id : null);
  const selectedIndex = rows.findIndex(step => step.id === selectedId);
  const selected = rows[selectedIndex];
  const key = `${execution.id}:${execution.lease_epoch ?? ""}:${selectedId ?? ""}:${selected?.captureUrl ?? ""}`;
  const capture = useCapture(selected?.captureUrl ?? null, key, retry);
  const blocked = capture?.status === "expired" || capture?.status === "forbidden";
  const number = (value: number) => new Intl.NumberFormat(locale).format(value);
  useEffect(() => {
    // Wait for the first available capture before pinning an automatic selection.
    if (rows.some(step => step.captureUrl) && selectedId && (selection?.executionId !== execution.id || !rows.some(step => step.id === selection.id))) setSelection({ executionId: execution.id, id: selectedId });
  }, [rows, selectedId, execution.id, selection]);
  function select(index: number, focus = false) {
    if (!rows[index]) return;
    setSelection({ executionId: execution.id, id: rows[index].id });
    if (focus) buttons.current[index]?.focus();
  }
  function actionLabel(id: string) {
    const action = steps?.find(step => step.id === id)?.action;
    return action && Object.hasOwn(editorActions, action) ? t(editorActions[action as keyof typeof editorActions]) : null;
  }
  function navigate(event: KeyboardEvent<HTMLElement>) {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    let index = selectedIndex;
    if (event.key === "ArrowDown") index += 1;
    else if (event.key === "ArrowUp") index -= 1;
    else if (event.key === "ArrowRight") index += locale === "ar" ? -1 : 1;
    else if (event.key === "ArrowLeft") index += locale === "ar" ? 1 : -1;
    else if (event.key === "Home") index = 0;
    else if (event.key === "End") index = rows.length - 1;
    else return;
    event.preventDefault();
    select(Math.max(0, Math.min(rows.length - 1, index)), Boolean((event.target as HTMLElement).closest(".execution-step-button")));
  }
  const error = capture?.status === "expired" ? "Votre session a expiré. Reconnectez-vous."
    : capture?.status === "forbidden" ? "L’accès à cette capture a été révoqué."
    : capture?.status === "missing" ? "Cette capture n’est plus disponible."
    : "Impossible de charger la capture.";
  return <section className={`execution-gallery ${compact ? "execution-gallery--compact" : ""}`} aria-labelledby={titleId} onKeyDown={navigate}>
    <div className="execution-gallery-heading"><h4 id={titleId}>{t("Captures des étapes")}</h4>{rows.length > 0 && <span>{t("Captures enregistrées : {count}", { count: number(rows.filter(step => step.captureUrl).length) })}</span>}</div>
    {!selected ? <p className="small-copy">{t("Les preuves apparaîtront lorsque le worker aura exécuté les étapes.")}</p> : <div className="execution-gallery-layout">
      <ol className="execution-step-list" role="list" aria-label={t("Captures des étapes")}>
        {rows.map((step, index) => <li key={`${execution.id}:${execution.lease_epoch}:${step.id}`}><button type="button" className="execution-step-button" ref={button => { buttons.current[index] = button; }} tabIndex={selectedId === step.id ? 0 : -1} aria-pressed={selectedId === step.id} aria-controls={previewId} onClick={() => select(index)}>
          <span className="execution-step-number"><bdi>{number(index + 1)}</bdi></span><Thumbnail step={step} blocked={blocked} retry={retry} /><span className="execution-step-copy"><strong><bdi>{step.label}</bdi></strong>{actionLabel(step.id) && <small className="execution-step-action">{actionLabel(step.id)}</small>}<StepState state={step.state} /></span>
        </button></li>)}
      </ol>
      <div className="execution-capture-preview" id={previewId}>
        <div className="execution-capture-heading"><div aria-live="polite" aria-atomic="true"><span>{t("Étape {current} sur {total}", { current: number(selectedIndex + 1), total: number(rows.length) })}</span><strong><bdi>{selected.label}</bdi></strong>{actionLabel(selected.id) && <span className="execution-capture-action">{actionLabel(selected.id)}</span>}<StepState state={selected.state} /></div><div className="execution-capture-navigation">
          <button type="button" className="icon-button" aria-label={t("Étape précédente")} disabled={selectedIndex === 0} onClick={() => select(selectedIndex - 1)}><span className="execution-arrow-previous"><Icon name="arrow" size={18} /></span></button>
          <button type="button" className="icon-button" aria-label={t("Étape suivante")} disabled={selectedIndex === rows.length - 1} onClick={() => select(selectedIndex + 1)}><Icon name="arrow" size={18} /></button>
        </div></div>
        <div className="execution-capture-stage" aria-busy={capture?.status === "loading"}>
          {capture?.status === "ready" && capture.url ? <img className="execution-capture-image" src={capture.url} alt={t("Capture de l’étape {step}", { step: selected.label })} /> : <div className="execution-capture-placeholder" role="status">
            <Icon name={capture && capture.status !== "loading" ? "warning" : "phone"} size={32} />
            <strong>{t(!capture ? "Aucune capture pour cette étape." : capture.status === "loading" ? "Chargement de la capture…" : "Capture indisponible")}</strong>
            {capture && capture.status !== "loading" && <><p>{t(error)}</p>{!blocked && <button type="button" className="button button--secondary" onClick={() => setRetry(value => value + 1)}><Icon name="refresh" size={16} />{t("Réessayer")}</button>}</>}
          </div>}
        </div>
        <div className="execution-capture-footer"><div>{selected.capturedAt && <span>{t("Capture enregistrée à {time}", { time: new Intl.DateTimeFormat(locale, { dateStyle: "short", timeStyle: "medium", calendar: "gregory" }).format(new Date(selected.capturedAt)) })}</span>}{selected.durationMs !== null && <span>{t("Durée : {duration}", { duration: new Intl.NumberFormat(locale, { style: "unit", unit: selected.durationMs >= 1000 ? "second" : "millisecond", unitDisplay: "short", maximumFractionDigits: selected.durationMs >= 1000 ? 2 : 0 }).format(selected.durationMs >= 1000 ? selected.durationMs / 1000 : selected.durationMs) })}</span>}</div>{selected.captureUrl && !blocked && <a href={selected.captureUrl} target="_blank" rel="noopener noreferrer">{t("Ouvrir la capture")}<span aria-hidden="true"> ↗</span></a>}</div>
      </div>
    </div>}
  </section>;
}
