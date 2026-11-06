"use client";

import type { Data } from "../../lib/console-types";
import { Empty } from "./shared";
import { Icon } from "./icons";
import { RunRows } from "./activity";

export function Overview({ data, onOpen, onLaunch, onAdd }: { data: Data; onOpen: (id: string) => void; onLaunch: () => void; onAdd: () => void }) {
  const metrics = [
    { label: "Téléphones déclarés", value: data.summary.devices_total, note: "dans votre flotte", href: "/telephones", icon: "phone" as const },
    { label: "Exécutions actives", value: data.summary.runs_active, note: "en cours ou en attente", href: "/activite", icon: "activity" as const },
    { label: "À vérifier", value: data.summary.runs_needs_review, note: "une décision est nécessaire", href: "/activite", icon: "warning" as const },
    { label: "Exécutions réussies", value: data.summary.runs_succeeded, note: "résultats conservés", href: "/activite", icon: "check" as const }
  ];
  return <>
    {data.summary.runs_needs_review > 0 && <div className="notice notice--warning"><Icon name="warning" /><span><strong>{data.summary.runs_needs_review} exécution{data.summary.runs_needs_review > 1 ? "s" : ""} à vérifier.</strong> Les appareils concernés restent protégés contre une nouvelle exécution.</span><a href="/activite">Consulter l’activité<Icon name="arrow" size={16} /></a></div>}
    <section className="metrics-strip" aria-label="État de la flotte">{metrics.map((metric) => <a href={metric.href} className="metric" key={metric.label}><div className="metric-label"><span>{metric.label}</span><Icon name={metric.icon} size={19} /></div><strong>{metric.value}</strong><span>{metric.note}</span></a>)}</section>
    <section className="surface"><div className="surface-heading"><div><h2>Activité récente</h2><p>Les dernières exécutions de votre espace de travail.</p></div><a className="text-button" href="/activite">Tout voir<Icon name="arrow" size={17} /></a></div>{data.runs.length ? <RunRows runs={data.runs.slice(0, 5)} onOpen={onOpen} /> : <Empty icon="activity" title="Prêt pour votre première exécution" action={<button className="button button--primary" onClick={data.devices.length ? onLaunch : onAdd}><Icon name={data.devices.length ? "play" : "plus"} size={18} />{data.devices.length ? "Lancer une automatisation" : "Ajouter un téléphone"}</button>}>Ajoutez un téléphone, choisissez un parcours, puis suivez son résultat depuis cette console.</Empty>}</section>
    <div className="overview-bottom"><section className="surface next-action"><span className="workflow-symbol"><Icon name="workflow" size={24} /></span><div><h2>Vos automatisations</h2><p>{data.summary.workflows_total ? `${data.summary.workflows_total} version${data.summary.workflows_total > 1 ? "s" : ""} publiée${data.summary.workflows_total > 1 ? "s" : ""}. Un même parcours peut cibler plusieurs téléphones.` : "Les parcours publiés seront disponibles pour toute votre flotte."}</p><a className="text-button" href="/automatisations">Choisir un parcours<Icon name="arrow" size={17} /></a></div></section><section className="surface next-action"><span className="secure-symbol"><Icon name="shield" size={24} /></span><div><h2>Un espace protégé</h2><p>Mot de passe et vérification en deux étapes protègent l’accès aux téléphones et aux résultats.</p><a className="text-button" href="/securite">Consulter la sécurité<Icon name="arrow" size={17} /></a></div></section></div>
  </>;
}
