"use client";

import { useT } from "../../lib/i18n";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { Icon } from "./icons";
import { formatDate, type Locale } from "../../lib/i18n-core";

export const statuses: Record<string, { label: string; tone: string }> = {
  queued: { label: "En attente", tone: "neutral" }, running: { label: "En cours", tone: "blue" },
  succeeded: { label: "Réussie", tone: "green" }, failed: { label: "Échouée", tone: "red" },
  cancelled: { label: "Annulée", tone: "neutral" }, needs_review: { label: "À vérifier", tone: "amber" },
  waiting_auth: { label: "Connexion requise", tone: "amber" }, recovering: { label: "Récupération", tone: "blue" },
  leased: { label: "Réservé", tone: "blue" }, verifying_state: { label: "Vérification", tone: "blue" },
  declared: { label: "Déclaré", tone: "neutral" }, busy: { label: "Occupé", tone: "blue" }
};
export function Badge({ status, cancelRequested = false }: { status: string; cancelRequested?: boolean }) {
  const t = useT();
  const item = cancelRequested && status === "running" ? { label: t("Arrêt demandé"), tone: "amber" } : statuses[status] ?? { label: status, tone: "neutral" };
  return <span className={`status-badge status-badge--${item.tone}`}><span className="status-dot" />{t(item.label)}</span>;
}
export function workflowName(id: string) {
  return id === "chrome-wikipedia-football" ? "Recherche Wikipédia" : id.replace(/[-_]/g, " ");
}
export function date(value: string, locale: Locale = "en", timeZone?: string) {
  return formatDate(value, locale, timeZone);
}
export function Empty({ icon = "phone", title, children, action }: { icon?: "phone" | "activity" | "workflow" | "search"; title: string; children: ReactNode; action?: ReactNode }) {
  return <div className="empty-state"><span className="empty-icon"><Icon name={icon} size={28} /></span><h3>{title}</h3><p>{children}</p>{action}</div>;
}
export function Dialog({ title, description, children, onClose, wide = false }: { title: string; description?: string; children: ReactNode; onClose: () => void; wide?: boolean }) {
  const t = useT();
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    const dialog = ref.current;
    dialog?.showModal();
    dialog?.querySelector<HTMLElement>("input:not([type=checkbox]), select, textarea")?.focus();
    return () => { dialog?.close(); trigger?.focus(); };
  }, []);
  return <dialog ref={ref} className={`console-dialog ${wide ? "console-dialog--wide" : ""}`} aria-labelledby={titleId} onCancel={(event) => { event.preventDefault(); onClose(); }}>
    <div className="dialog-header"><div><h2 id={titleId}>{title}</h2>{description && <p>{description}</p>}</div><button type="button" className="icon-button" aria-label={t("Fermer")} onClick={onClose}><Icon name="close" /></button></div>
    {children}
  </dialog>;
}
export function ErrorNotice({ message }: { message: string }) {
  const t = useT(); return <div className="notice notice--error" role="alert"><Icon name="warning" /><span>{t(message)}</span></div>; }
