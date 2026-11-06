"use client";

import type { Workflow } from "../../lib/console-types";
import { Empty, workflowName } from "./shared";
import { Icon } from "./icons";

export function Workflows({ workflows, onLaunch }: { workflows: Workflow[]; onLaunch: (workflow: Workflow) => void }) {
  return <>
    <div className="section-heading"><div><h2>Des parcours prêts à exécuter</h2><p>Choisissez une version, puis les téléphones à cibler.</p></div><a className="button button--secondary" href="/validation"><Icon name="archive" />Voir le banc de validation</a></div>
    {!workflows.length ? <section className="surface"><Empty icon="workflow" title="Aucune automatisation publiée">Les parcours publiés par l’API apparaîtront ici. Le premier parcours prévu recherche « football » sur Wikipédia dans Chrome.</Empty></section> : <section className="surface workflow-list">{workflows.map((workflow) => <article className="workflow-row" key={`${workflow.workflow_id}:${workflow.version}`}><div className="workflow-symbol"><Icon name="workflow" size={26} /></div><div className="workflow-copy"><div className="title-with-badge"><h3>{workflowName(workflow.workflow_id)}</h3><span className="version-tag">Version {workflow.version}</span></div><p>{workflow.workflow_id === "chrome-wikipedia-football" ? "Ouvrir Chrome, rechercher football sur Wikipédia et vérifier le résultat." : workflow.workflow_id}</p><div className="metadata-line"><span>{workflow.steps.length} étapes</span><span>{workflow.recovery_budget === 0 ? "Parcours scripté · sans LLM" : `${workflow.recovery_budget} récupérations maximum`}</span></div><details className="steps-disclosure"><summary>Consulter les étapes</summary><ol className="workflow-steps">{workflow.steps.map((step) => <li key={step.id}><span>{step.id.replace(/-/g, " ")}</span><code>{step.action}</code></li>)}</ol></details></div><button className="button button--primary" onClick={() => onLaunch(workflow)}><Icon name="play" size={18} />Lancer</button></article>)}</section>}
  </>;
}
