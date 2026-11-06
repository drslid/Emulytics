"use client";
import type { Device } from "../../lib/console-types";
import { useT } from "../../lib/i18n";

const labels = {
  connected: "Connecté",
  worker_offline: "Worker indisponible",
  not_connected: "Appareil introuvable",
  unauthorized: "Autorisation Android requise",
  offline: "Android hors ligne",
  unknown: "Connexion non vérifiée"
};
export function DeviceConnection({ device }: { device: Device }) {
  const t = useT();
  const state = device.connection_status ?? "unknown";
  return <span className={`status-badge status-badge--${state === "connected" ? "green" : "amber"}`}><span className="status-dot" />{t(labels[state])}</span>;
}
