"use client";

import { useState } from "react";
import type { Run } from "../../lib/console-types";
import { Badge, Empty, date, workflowName } from "./shared";
import { Icon } from "./icons";

export function RunRows({ runs, onOpen }: { runs: Run[]; onOpen: (id: string) => void }) {
  return <div className="table-scroll" role="region" aria-label="Liste des exécutions" tabIndex={0}><table className="data-table"><caption className="sr-only">Exécutions récentes et leur résultat</caption><thead><tr><th>Automatisation</th><th>État</th><th>Téléphones</th><th>Lancement</th><th><span className="sr-only">Détail</span></th></tr></thead><tbody>{runs.map((run) => <tr key={run.id}><th scope="row"><button className="row-link" onClick={() => onOpen(run.id)}>{workflowName(run.workflow_id)}<span>Version {run.workflow_version} · {run.id.slice(0, 8)}</span></button></th><td><Badge status={run.status} cancelRequested={run.cancel_requested} /></td><td>{run.device_ids.length}</td><td className="nowrap">{date(run.created_at)}</td><td><button className="icon-button" aria-label={`Ouvrir l’exécution ${run.id.slice(0, 8)}`} onClick={() => onOpen(run.id)}><Icon name="arrow" size={18} /></button></td></tr>)}</tbody></table></div>;
}

export function Activity({ runs, total, offset, onPage, onOpen, onLaunch }: { runs: Run[]; total: number; offset: number; onPage: (offset: number) => void; onOpen: (id: string) => void; onLaunch: () => void }) {
  const [status, setStatus] = useState("all");
  const [search, setSearch] = useState("");
  const visible = runs.filter((run) => (status === "all" || run.status === status) && `${run.workflow_id} ${run.id} ${run.device_ids.join(" ")}`.toLocaleLowerCase("fr").includes(search.toLocaleLowerCase("fr")));
  return <>
    <div className="section-heading"><div><h2>Toutes les exécutions</h2><p>Du lancement aux preuves, un historique partagé par toute la flotte.</p></div><a className="text-button" href="/validation"><Icon name="archive" size={18} />Banc de validation</a></div>
    <section className="surface"><div className="table-toolbar"><label className="search-field"><Icon name="search" /><input type="search" aria-label="Rechercher une exécution" placeholder="Rechercher dans cette page…" value={search} onChange={(event) => setSearch(event.target.value)} /></label><label className="filter-field"><span>État</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">Tous les états</option><option value="running">En cours</option><option value="queued">En attente</option><option value="needs_review">À vérifier</option><option value="succeeded">Réussies</option><option value="failed">Échouées</option><option value="cancelled">Annulées</option></select></label></div>
      {!runs.length ? <Empty icon="activity" title="L’activité commence ici" action={<button className="button button--primary" onClick={onLaunch}><Icon name="play" size={18} />Lancer une automatisation</button>}>Vos exécutions et leurs résultats apparaîtront ici dès le premier lancement.</Empty> : !visible.length ? <Empty icon="search" title="Aucun résultat">Essayez un autre filtre ou une autre recherche.</Empty> : <RunRows runs={visible} onOpen={onOpen} />}
      <div className="table-footer"><span>{total ? `${offset + 1}–${Math.min(offset + runs.length, total)} sur ${total}` : "0 exécution"}{total > 100 ? " · filtres sur cette page" : ""}</span><div className="pagination"><button className="text-button" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - 100))}>Précédent</button><button className="text-button" disabled={offset + runs.length >= total} onClick={() => onPage(offset + 100)}>Suivant</button></div></div>
    </section>
  </>;
}
