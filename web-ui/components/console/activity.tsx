"use client";

import { useLocale } from "../../lib/i18n";

import { useState } from "react";
import type { Run } from "../../lib/console-types";
import { Badge, Empty, date, workflowName } from "./shared";
import { Icon } from "./icons";

export function RunRows({ runs, onOpen }: { runs: Run[]; onOpen: (id: string) => void }) {
  const { t, locale } = useLocale();
  return <div className="table-scroll" role="region" aria-label={t("Liste des exécutions")} tabIndex={0}><table className="data-table"><caption className="sr-only">{t("Exécutions récentes et leur résultat")}</caption><thead><tr><th>{t("Automatisation")}</th><th>{t("État")}</th><th>{t("Téléphones")}</th><th>{t("Lancement")}</th><th><span className="sr-only">{t("Détail")}</span></th></tr></thead><tbody>{runs.map((run) => <tr key={run.id}><th scope="row"><button className="row-link" onClick={() => onOpen(run.id)}>{t(workflowName(run.workflow_id))}<span>{t("Version")} {run.workflow_version} · {run.id.slice(0, 8)}</span></button></th><td><Badge status={run.status} cancelRequested={run.cancel_requested} /></td><td>{run.device_ids.length}</td><td className="nowrap">{date(run.created_at, locale)}</td><td><button className="icon-button" aria-label={t("Ouvrir l’exécution {id}", {id: run.id.slice(0, 8)})} onClick={() => onOpen(run.id)}><Icon name="arrow" size={18} /></button></td></tr>)}</tbody></table></div>;
}

export function Activity({ runs, total, offset, onPage, onOpen, onLaunch, canLaunch = true }: { runs: Run[]; total: number; offset: number; onPage: (offset: number) => void; onOpen: (id: string) => void; onLaunch: () => void; canLaunch?: boolean }) {
  const { t, locale } = useLocale();
  const [status, setStatus] = useState("all");
  const [search, setSearch] = useState("");
  const visible = runs.filter((run) => (status === "all" || run.status === status) && `${run.workflow_id} ${run.id} ${run.device_ids.join(" ")}`.toLocaleLowerCase(locale).includes(search.toLocaleLowerCase(locale)));
  return <>
    <div className="section-heading"><div><h2>{t("Toutes les exécutions")}</h2><p>{t("Du lancement aux preuves, un historique partagé par toute la flotte.")}</p></div><a className="text-button" href="/validation"><Icon name="archive" size={18} />{t("Banc de validation")}</a></div>
    <section className="surface"><div className="table-toolbar"><label className="search-field"><Icon name="search" /><input type="search" aria-label={t("Rechercher une exécution")} placeholder={t("Rechercher dans cette page…")} value={search} onChange={(event) => setSearch(event.target.value)} /></label><label className="filter-field"><span>{t("État")}</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">{t("Tous les états")}</option><option value="running">{t("En cours")}</option><option value="queued">{t("En attente")}</option><option value="needs_review">{t("À vérifier")}</option><option value="succeeded">{t("Réussies")}</option><option value="failed">{t("Échouées")}</option><option value="cancelled">{t("Annulées")}</option></select></label></div>
      {!runs.length ? <Empty icon="activity" title={t("L’activité commence ici")} action={canLaunch ? <button className="button button--primary" onClick={onLaunch}><Icon name="play" size={18} />{t("Lancer une automatisation")}</button> : undefined}>{t("Vos exécutions et leurs résultats apparaîtront ici dès le premier lancement.")}</Empty> : !visible.length ? <Empty icon="search" title={t("Aucun résultat")}>{t("Essayez un autre filtre ou une autre recherche.")}</Empty> : <RunRows runs={visible} onOpen={onOpen} />}
      <div className="table-footer"><span>{total ? t("{start}–{end} sur {total}", { start: offset + 1, end: Math.min(offset + runs.length, total), total }) : t("0 exécution")}{total > 100 ? t(" · filtres sur cette page") : ""}</span><div className="pagination"><button className="text-button" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - 100))}>{t("Précédent")}</button><button className="text-button" disabled={offset + runs.length >= total} onClick={() => onPage(offset + 100)}>{t("Suivant")}</button></div></div>
    </section>
  </>;
}
