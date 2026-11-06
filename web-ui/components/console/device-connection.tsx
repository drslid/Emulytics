"use client";
import type { Device } from "../../lib/console-types";
import { useLocale, useT } from "../../lib/i18n";
import { formatDate } from "../../lib/i18n-core";

const labels = {
  connected: "Connecté",
  worker_offline: "Aucun worker actif sur cet hôte",
  not_connected: "Appareil introuvable",
  unauthorized: "Autorisation Android requise",
  offline: "Android hors ligne",
  unknown: "Connexion non vérifiée"
};
export function DeviceConnection({ device }: { device: Device }) {
  const t = useT();
  const { locale } = useLocale();
  const state = device.connection_status ?? "unknown";
  const seen = device.worker_last_seen_at;
  const detail = state === "worker_offline" ? seen && Number.isFinite(Date.parse(seen))
    ? t("Dernier signal de l’hôte {host} : {time}.", {host:device.host_id,time:formatDate(seen,locale)})
    : t("Aucun signal de worker reçu pour l’hôte {host}.", {host:device.host_id}) : null;
  return <span className="device-connection"><span className={`status-badge status-badge--${state === "connected" ? "green" : "amber"}`}><span className="status-dot" />{t(labels[state])}</span>{detail && <small className="device-connection-detail" dir="auto">{detail}</small>}</span>;
}
