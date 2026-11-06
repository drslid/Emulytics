"use client";

import { useEffect, useId, useRef, useState } from "react";
import { api, ApiError } from "../../lib/client-api";
import { dashboardOutcomes, dayTotal, parseDashboardCapacity, parseDashboardSnapshot, percentOf, type DashboardCapacity, type DashboardSnapshot } from "../../lib/dashboard";
import { useLocale, useT } from "../../lib/i18n";
import { ErrorNotice } from "./shared";
import { Icon } from "./icons";

type Measurements = { activity: DashboardSnapshot; capacity: DashboardCapacity; received: number };

export function DashboardCharts() {
  const t = useT(), { locale } = useLocale(), id = useId();
  const [data, setData] = useState<Measurements | null>(null), [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false), [paused, setPaused] = useState(false), [now, setNow] = useState(0);
  const retry = useRef<() => void>(() => {});

  useEffect(() => {
    let alive = true, sequence = 0, pending: number | null = null;
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    async function load() {
      if (!alive || pending !== null || document.visibilityState === "hidden") return;
      const request = ++sequence; pending = request; setRefreshing(true);
      try {
        const [activity, capacity] = await Promise.all([
          api<unknown>(`console/dashboard?timezone=${encodeURIComponent(timezone)}`),
          api<unknown>("console/monitor?window=7d"),
        ]);
        const measurements = { activity: parseDashboardSnapshot(activity), capacity: parseDashboardCapacity(capacity), received: Date.now() };
        if (!alive || request !== sequence) return;
        setData(measurements); setNow(measurements.received); setError("");
      } catch (failure) {
        if (!alive || request !== sequence) return;
        setError(failure instanceof ApiError ? failure.message : "Les mesures sont indisponibles. Les dernières données sont conservées.");
      } finally {
        if (pending === request) { pending = null; if (alive) setRefreshing(false); }
      }
    }
    function visibility() {
      const hidden = document.visibilityState === "hidden"; setPaused(hidden);
      if (hidden) { sequence++; pending = null; setRefreshing(false); }
      else void load();
    }
    retry.current = () => void load(); visibility();
    const timer = setInterval(() => { setNow(Date.now()); void load(); }, 10_000);
    document.addEventListener("visibilitychange", visibility);
    return () => { alive = false; sequence++; pending = null; clearInterval(timer); document.removeEventListener("visibilitychange", visibility); retry.current = () => {}; };
  }, []);

  const stale = !!data && (!!error || now - data.received > 20_000);
  const number = (value: number | null) => value === null ? "—" : new Intl.NumberFormat(locale).format(value);
  const timestamp = (value: string) => new Intl.DateTimeFormat(locale, { dateStyle: "short", timeStyle: "medium", timeZone: data?.activity.timezone, calendar: "gregory" }).format(new Date(value));
  const dayDate = (value: string, options: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat(locale, { ...options, timeZone: "UTC", calendar: "gregory" }).format(new Date(value + "T12:00:00Z"));
  const max = data ? Math.max(...data.activity.days.map(dayTotal), 0) : 0;
  const workers = data?.capacity.workers, devices = data?.capacity.devices;
  let donutOffset = 0;

  return <section className="dashboard-charts" aria-labelledby={`${id}-heading`}>
    <div className="dashboard-chart-heading"><div><h2 id={`${id}-heading`}>{t("Tendances de votre flotte")}</h2><p>{t("Les graphiques comptent les exécutions par appareil ; les indicateurs ci-dessus comptent les lancements.")}</p></div>
      <button type="button" className="text-button" disabled={refreshing || paused} onClick={() => retry.current()}><Icon name="refresh" size={15} />{t(refreshing ? "Actualisation…" : "Actualiser")}</button>
    </div>
    <div className="dashboard-period"><span>{t("Sept jours calendaires, journée en cours incluse.")}</span>{data && <><span>{t("Période : {start} – {end}", { start: dayDate(data.activity.days[0].date, { dateStyle: "medium" }), end: dayDate(data.activity.days[6].date, { dateStyle: "medium" }) })}</span><span>{t("Fuseau : {timezone}", { timezone: data.activity.timezone })}</span></>}</div>
    {(error || stale) && <ErrorNotice message={t(error || "Les mesures sont indisponibles. Les dernières données sont conservées.")} />}
    {data && <div className="dashboard-freshness"><span className={`status-badge status-badge--${stale || paused ? "amber" : "green"}`} role="status"><span className="status-dot" />{t(paused ? "En pause" : stale ? "Mesures périmées" : "Signal récent")}</span><span>{t("Dernière mesure")} : {timestamp(data.activity.observed_at)}</span></div>}
    {!data ? <section className="surface dashboard-charts-loading" role="status" aria-busy={refreshing}>{t(refreshing || !error ? "Chargement des graphiques…" : "Les mesures sont indisponibles. Les dernières données sont conservées.")}{error && <button type="button" className="button button--secondary" disabled={refreshing} onClick={() => retry.current()}>{t("Réessayer")}</button>}</section> : <div className="dashboard-chart-grid tw:grid tw:grid-cols-1 tw:gap-5 tw:min-[700px]:grid-cols-2 tw:min-[1300px]:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1.1fr)]" data-stale={stale || paused ? "true" : "false"}>
      <section className="surface dashboard-chart-card dashboard-chart-activity tw:min-[700px]:col-span-2 tw:min-[1300px]:col-span-1" aria-labelledby={`${id}-activity`}>
        <h3 id={`${id}-activity`}>{t("Activité quotidienne")}</h3><p>{t("Exécutions terminées par jour")}</p>
        <div className="dashboard-activity-bars" dir="ltr" role="group" aria-label={t("Exécutions terminées par jour")}>{data.activity.days.map(day => {
          const total = dayTotal(day), summary = `${dayDate(day.date, { dateStyle: "full" })} · ${dashboardOutcomes.map(outcome => `${t(outcome.label)} : ${number(day[outcome.key])}`).join(" · ")}`;
          return <div className="dashboard-day" key={day.date} role="img" aria-label={summary} title={summary}><strong>{number(total)}</strong><div className="dashboard-bar-track"><div className="dashboard-bar-stack" style={{ height: `${percentOf(total, max) ?? 0}%` }}>{dashboardOutcomes.map(outcome => <span key={outcome.key} className={`dashboard-outcome--${outcome.color}`} style={{ height: `${percentOf(day[outcome.key], total) ?? 0}%` }} />)}</div></div><span className="dashboard-day-number">{dayDate(day.date, { day: "numeric" })}</span><span className="dashboard-weekday">{dayDate(day.date, { weekday: "short" })}</span></div>;
        })}</div>
        {!data.activity.totals.finished && <p className="dashboard-empty">{t("Aucune exécution terminée sur ces sept jours.")}</p>}
        <details className="dashboard-data"><summary>{t("Voir les données")}</summary><div className="table-scroll" role="region" tabIndex={0} aria-label={t("Exécutions terminées par jour")}><table className="data-table dashboard-data-table"><caption className="sr-only">{t("Exécutions terminées par jour")}</caption><thead><tr><th scope="col">{t("Date")}</th>{dashboardOutcomes.map(outcome => <th scope="col" key={outcome.key}>{t(outcome.label)}</th>)}<th scope="col">{t("Terminées")}</th></tr></thead><tbody>{data.activity.days.map(day => <tr key={day.date}><th scope="row">{dayDate(day.date, { dateStyle: "medium" })}</th>{dashboardOutcomes.map(outcome => <td key={outcome.key}>{number(day[outcome.key])}</td>)}<td>{number(dayTotal(day))}</td></tr>)}</tbody><tfoot><tr><th scope="row">{t("7 jours")}</th>{dashboardOutcomes.map(outcome => <td key={outcome.key}>{number(data.activity.totals[outcome.key])}</td>)}<td>{number(data.activity.totals.finished)}</td></tr></tfoot></table></div></details>
      </section>
      <section className="surface dashboard-chart-card" aria-labelledby={`${id}-outcomes`}><h3 id={`${id}-outcomes`}>{t("Répartition des résultats")}</h3><p>{t("7 jours")}</p>
        <svg className="dashboard-donut" viewBox="0 0 140 140" role="img" aria-label={`${number(data.activity.totals.finished)} ${t("Terminées")}`}><circle className="dashboard-donut-track" cx="70" cy="70" r="50" fill="none" strokeWidth="16" />{dashboardOutcomes.map(outcome => {
          const percentage = percentOf(data.activity.totals[outcome.key], data.activity.totals.finished) ?? 0, offset = donutOffset; donutOffset += percentage;
          return percentage ? <circle key={outcome.key} className={`dashboard-outcome-stroke--${outcome.color}`} cx="70" cy="70" r="50" fill="none" strokeWidth="16" pathLength="100" strokeDasharray={`${percentage} ${100 - percentage}`} strokeDashoffset={-offset} transform="rotate(-90 70 70)" /> : null;
        })}<text x="70" y="69" className="dashboard-donut-total" textAnchor="middle" aria-hidden="true">{number(data.activity.totals.finished)}</text><text x="70" y="88" className="dashboard-donut-label" textAnchor="middle" aria-hidden="true">{t("Terminées")}</text></svg>
        <ul className="dashboard-outcome-legend">{dashboardOutcomes.map(outcome => <li key={outcome.key}><span className={`dashboard-legend-dot dashboard-outcome--${outcome.color}`} aria-hidden="true" /><span>{t(outcome.label)}</span><strong><bdi>{number(data.activity.totals[outcome.key])}</bdi></strong></li>)}</ul>
      </section>
      <section className="surface dashboard-chart-card dashboard-chart-capacity" aria-labelledby={`${id}-capacity`}><h3 id={`${id}-capacity`}>{t("Capacité actuelle")}</h3><p>{t("Dernière mesure")} : {timestamp(data.capacity.observed_at)}</p>
        <div className="dashboard-capacity-block"><div className="dashboard-capacity-label"><span>{t("Workers occupés / actifs")}</span><strong><bdi dir="ltr">{number(workers?.busy ?? null)} / {number(workers?.total ?? null)}</bdi></strong></div><div className="dashboard-capacity-bar" aria-hidden="true"><span className="dashboard-worker-busy" style={{ width: `${percentOf(workers?.busy ?? null, workers?.total ?? null) ?? 0}%` }} /><span className="dashboard-worker-idle" style={{ width: `${percentOf(workers?.idle ?? null, workers?.total ?? null) ?? 0}%` }} /></div><div className="dashboard-capacity-detail"><span>{t("Workers occupés")} : {number(workers?.busy ?? null)}</span><span>{t("Workers libres")} : {number(workers?.idle ?? null)}</span></div>{(!workers || !workers.total) && <p className="dashboard-empty">{t("Aucune capacité confirmée")}</p>}</div>
        <p className="dashboard-declared">{t("Téléphones déclarés")} : <strong>{number(devices?.total ?? null)}</strong></p>
        {[{ label: "Appareils prêts", value: devices?.ready ?? null, className: "dashboard-device-ready" }, { label: "Appareils connectés", value: devices?.connected ?? null, className: "dashboard-device-connected" }].map(item => <div className="dashboard-capacity-block" key={item.label}><div className="dashboard-capacity-label"><span>{t(item.label)}</span><strong><bdi dir="ltr">{number(item.value)} / {number(devices?.total ?? null)}</bdi></strong></div><div className="dashboard-capacity-bar" aria-hidden="true"><span className={item.className} style={{ width: `${percentOf(item.value, devices?.total ?? null) ?? 0}%` }} /></div></div>)}
        {!!data.capacity.unconfirmedDevices && <p className="dashboard-capacity-note">{t("{n} connexions non confirmées", { n: number(data.capacity.unconfirmedDevices) })}</p>}
        <p className="dashboard-capacity-note">{t("Chaque worker dispose d’un emplacement d’exécution. Le nombre d’appareils connectés reste une mesure distincte.")}</p>
      </section>
    </div>}
  </section>;
}
