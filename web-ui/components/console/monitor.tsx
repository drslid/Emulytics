"use client";
import { useEffect, useState } from "react";
import { useLocale, useT } from "../../lib/i18n";
import { date, ErrorNotice } from "./shared";
import { Icon } from "./icons";

type Signal = {
  component: string;
  instance_id: string;
  host_id: string | null;
  status: string;
  live: boolean;
  last_seen_at: string | null;
};
type Snapshot = {
  observed_at: string;
  database: { status: string; latency_ms: number };
  web: { status: string };
  services: Signal[];
  queues: { status: string; count: number }[];
  hosts: { host_id: string; devices: number }[];
  leases: { active: number; needs_review: number };
  schedules: { enabled: number; next_run_at: string | null };
};
export function Monitor() {
  const t = useT(),
    { locale } = useLocale();
  const [data, setData] = useState<Snapshot | null>(null),
    [connected, setConnected] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    const stream = new EventSource("/api/control/console/monitor/stream");
    stream.onmessage = (event) => {
      try {
        setData(JSON.parse(event.data));
        setConnected(true);
        setError("");
      } catch {
        setConnected(false);
      }
    };
    stream.onerror = () => {
      setConnected(false);
      setError(
        "Le flux de monitoring est interrompu. Reconnexion automatique…",
      );
    };
    stream.addEventListener("unavailable", () => {
      setConnected(false);
      setError(
        "Les mesures sont indisponibles. Les dernières données sont conservées.",
      );
    });
    stream.addEventListener("revoked", () => {
      stream.close();
      window.location.assign("/connexion");
    });
    return () => stream.close();
  }, []);
  const node = (label: string, status: boolean | undefined, detail: string) => (
    <div
      className={`architecture-node ${connected && status ? "architecture-node--ready" : "architecture-node--inactive"}`}
    >
      <span className="status-dot" />
      <strong>{t(label)}</strong>
      <span>
        {connected
          ? t(status ? "Disponible" : "Indisponible")
          : t("État non confirmé")}
      </span>
      <small>{detail}</small>
    </div>
  );
  return (
    <>
      {error && <ErrorNotice message={t(error)} />}
      <div className="section-heading">
        <div>
          <h2>{t("Architecture en direct")}</h2>
          <p>
            {t(
              "Signaux des services, files d’attente et workers. Actualisation continue toutes les deux secondes.",
            )}
          </p>
        </div>
        <span
          className={`status-badge status-badge--${connected ? "green" : "amber"}`}
        >
          <span className="status-dot" />
          {t(connected ? "En direct" : "Reconnexion…")}
        </span>
      </div>
      <section
        className="surface architecture-board"
        aria-label={t("État de l’architecture")}
      >
        {node(
          "Interface web",
          data?.web.status === "ready",
          data?.web.status === "unconfigured"
            ? t("Sonde non configurée")
            : t("Console de pilotage mobile"),
        )}
        <div className="architecture-link" aria-hidden="true">
          ↓
        </div>
        {node(
          "API de contrôle",
          data?.services.some((s) => s.component === "api" && s.live),
          t("Sessions, droits et commandes"),
        )}
        <div className="architecture-branches">
          <div>
            {node(
              "PostgreSQL",
              data?.database.status === "ready",
              data ? `${data.database.latency_ms} ms` : "—",
            )}
          </div>
          <div>
            {node(
              "Ordonnanceur",
              data?.services.some((s) => s.component === "scheduler" && s.live),
              data
                ? t("{n} planifications actives", { n: data.schedules.enabled })
                : "—",
            )}
          </div>
          <div>
            {node(
              "Workers Android",
              data?.services.some((s) => s.component === "worker" && s.live),
              data
                ? t("{n} workers actifs", {
                    n: data.services.filter(
                      (s) => s.component === "worker" && s.live,
                    ).length,
                  })
                : "—",
            )}
          </div>
        </div>
        <p className="architecture-footnote">
          {t(
            "Un appareil déclaré ne prouve pas une connexion Android. Un worker absent ne peut prendre aucune exécution en charge.",
          )}
        </p>
      </section>
      {data && (
        <>
          <div className="monitor-metrics">
            <section className="surface metric-card">
              <Icon name="clock" />
              <strong>
                {data.queues
                  .filter((q) => q.status === "queued")
                  .reduce((n, q) => n + q.count, 0)}
              </strong>
              <span>{t("Exécutions en attente")}</span>
            </section>
            <section className="surface metric-card">
              <Icon name="play" />
              <strong>{data.leases.active}</strong>
              <span>{t("Appareils réservés")}</span>
            </section>
            <section className="surface metric-card">
              <Icon name="warning" />
              <strong>{data.leases.needs_review}</strong>
              <span>{t("Appareils à vérifier")}</span>
            </section>
          </div>
          <section className="surface">
            <div className="section-heading table-heading">
              <h2>{t("Signaux des services")}</h2>
              <span>
                {t("Dernière mesure")} : {date(data.observed_at, locale)}
              </span>
            </div>
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>{t("Service")}</th>
                    <th>{t("Instance / hôte")}</th>
                    <th>{t("État")}</th>
                    <th>{t("Dernier signal")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.services.map((service) => (
                    <tr key={`${service.component}:${service.instance_id}`}>
                      <td>
                        <strong>
                          {t(
                            {
                              api: "API de contrôle",
                              scheduler: "Ordonnanceur",
                              worker: "Worker Android",
                            }[service.component] ?? service.component,
                          )}
                        </strong>
                      </td>
                      <td>
                        <code dir="ltr">
                          {service.host_id ?? service.instance_id}
                        </code>
                      </td>
                      <td>
                        {t(
                          !connected
                            ? "État non confirmé"
                            : service.live
                              ? "Disponible"
                              : service.status === "missing"
                                ? "Non démarré"
                                : "Signal périmé",
                        )}
                      </td>
                      <td>
                        {service.last_seen_at
                          ? date(service.last_seen_at, locale)
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          <section className="surface host-list">
            <h2>{t("Hôtes et appareils déclarés")}</h2>
            {data.hosts.length ? (
              data.hosts.map((host) => (
                <p key={host.host_id}>
                  <code dir="ltr">{host.host_id}</code>
                  <span>{t("{n} appareils", { n: host.devices })}</span>
                </p>
              ))
            ) : (
              <p>{t("Aucun appareil enregistré.")}</p>
            )}
          </section>
        </>
      )}
      {!data && (
        <section className="surface loading-state" role="status">
          {t("Connexion aux mesures en direct…")}
        </section>
      )}
    </>
  );
}
