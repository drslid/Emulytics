"use client";

import { useT } from "../../lib/i18n";

import type { Data } from "../../lib/console-types";
import { Empty } from "./shared";
import { Icon } from "./icons";
import { RunRows } from "./activity";
import { DashboardCharts } from "./dashboard-charts";

export function Overview({ data, onOpen, onLaunch, onAdd, canAdd = true, canLaunch = true }: { data: Data; onOpen: (id: string) => void; onLaunch: () => void; onAdd: () => void; canAdd?: boolean; canLaunch?: boolean }) {
  const t = useT();
  const metrics = [
    { label: t("Téléphones déclarés"), value: data.summary.devices_total, note: t("dans votre flotte"), href: "/telephones", icon: "phone" as const },
    { label: t("Exécutions actives"), value: data.summary.runs_active, note: t("en cours ou en attente"), href: "/activite", icon: "activity" as const },
    { label: t("À vérifier"), value: data.summary.runs_needs_review, note: t("une décision est nécessaire"), href: "/activite", icon: "warning" as const },
    { label: t("Exécutions réussies"), value: data.summary.runs_succeeded, note: t("résultats conservés"), href: "/activite", icon: "check" as const }
  ];
  return <>
    {data.summary.runs_needs_review > 0 && <div className="notice notice--warning"><Icon name="warning" /><span><strong>{t("{count} exécution(s) à vérifier.", {count: data.summary.runs_needs_review})}</strong> {t("Les appareils concernés restent protégés contre une nouvelle exécution.")}</span><a href="/activite">{t("Consulter l’activité")}<Icon name="arrow" size={16} /></a></div>}
    <section className="metrics-strip" aria-label={t("État de la flotte")}>{metrics.map((metric) => <a href={metric.href} className="metric" key={metric.label}><div className="metric-label"><span>{metric.label}</span><Icon name={metric.icon} size={19} /></div><strong>{metric.value}</strong><span>{metric.note}</span></a>)}</section>
    <DashboardCharts />
    <section className="surface"><div className="surface-heading"><div><h2>{t("Activité récente")}</h2><p>{t("Les dernières exécutions de votre espace de travail.")}</p></div><a className="text-button" href="/activite">{t("Tout voir")}<Icon name="arrow" size={17} /></a></div>{data.runs.length ? <RunRows runs={data.runs.slice(0, 5)} onOpen={onOpen} /> : <Empty icon="activity" title={t("Prêt pour votre première exécution")} action={(data.devices.length ? canLaunch : canAdd) ? <button className="button button--primary" onClick={data.devices.length ? onLaunch : onAdd}><Icon name={data.devices.length ? "play" : "plus"} size={18} />{data.devices.length ? t("Lancer une automatisation") : t("Ajouter un téléphone")}</button> : undefined}>{t("Ajoutez un téléphone, choisissez un parcours, puis suivez son résultat depuis cette console.")}</Empty>}</section>
    <div className="overview-bottom"><section className="surface next-action"><span className="workflow-symbol"><Icon name="workflow" size={24} /></span><div><h2>{t("Vos automatisations")}</h2><p>{data.summary.workflows_total ? t("{count} version(s) publiée(s). Un même parcours peut cibler plusieurs téléphones.", {count: data.summary.workflows_total}) : t("Les parcours publiés seront disponibles pour toute votre flotte.")}</p><a className="text-button" href="/automatisations">{t("Choisir un parcours")}<Icon name="arrow" size={17} /></a></div></section><section className="surface next-action"><span className="secure-symbol"><Icon name="shield" size={24} /></span><div><h2>{t("Un espace protégé")}</h2><p>{t("Mot de passe et vérification en deux étapes protègent l’accès aux téléphones et aux résultats.")}</p><a className="text-button" href="/profil#securite">{t("Consulter la sécurité")}<Icon name="arrow" size={17} /></a></div></section></div>
  </>;
}
