"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../lib/client-api";
import { useT } from "../../lib/i18n";
import type { Page, Recipe, Workflow } from "../../lib/console-types";
import { Empty, ErrorNotice, workflowName } from "./shared";
import { Icon } from "./icons";
import { RecipeEditor } from "./recipe-editor";

export function Workflows({
  workflows,
  onLaunch,
  onSchedule,
  canBuild,
  canLaunch,
  onChanged,
}: {
  workflows: Workflow[];
  onLaunch: (workflow: Workflow) => void;
  onSchedule: (workflow: Workflow) => void;
  canBuild: boolean;
  canLaunch: boolean;
  onChanged: () => void;
}) {
  const t = useT();
  const [page, setPage] = useState<Page<Recipe> | null>(null),
    [editing, setEditing] = useState<Recipe | "new" | null>(null),
    [error, setError] = useState(""),
    [loadError, setLoadError] = useState(""),
    [loading, setLoading] = useState(canBuild),
    [busy, setBusy] = useState(false);
  const sequence = useRef(0), mounted = useRef(false), requestedOffset = useRef(0);
  const recipes = page?.items ?? [], total = page?.total ?? recipes.length, offset = page?.offset ?? 0;
  const load = useCallback(async (pageOffset = 0) => {
    if (!canBuild) return;
    const request = ++sequence.current;
    requestedOffset.current = pageOffset; setLoading(true); setLoadError("");
    try {
      const result = await api<Page<Recipe>>(`console/recipes?limit=100&offset=${pageOffset}`);
      if (!mounted.current || request !== sequence.current) return;
      setPage(result);
    } catch (e) {
      if (mounted.current && request === sequence.current) setLoadError((e as Error).message);
    } finally { if (mounted.current && request === sequence.current) setLoading(false); }
  }, [canBuild]);
  useEffect(() => {
    mounted.current = true;
    void load();
    return () => { mounted.current = false; sequence.current++; };
  }, [load]);
  function publishedName(workflow: Workflow) {
    return workflow.name || recipes.find(recipe => recipe.workflow_id === workflow.workflow_id)?.name || t(workflowName(workflow.workflow_id));
  }
  function publishedInstructions(workflow: Workflow) {
    return workflow.instructions || recipes.find(recipe => recipe.workflow_id === workflow.workflow_id)?.instructions ||
      (workflow.workflow_id === "chrome-wikipedia-football"
        ? t("Ouvrir Chrome, rechercher football sur Wikipédia et vérifier le résultat.")
        : t("Étapes du parcours {name}.", { name: publishedName(workflow) }));
  }
  async function editPublished(workflow: Workflow) {
    setBusy(true); setError("");
    try {
      const recipe = await api<Recipe>("console/recipes/from-workflow", {
        workflow_id: workflow.workflow_id, version: workflow.version,
        name: Array.from(publishedName(workflow)).slice(0, 120).join(""), instructions: publishedInstructions(workflow),
      });
      setEditing(recipe);
      await load();
    } catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }
  async function publish(recipe: Recipe) {
    setBusy(true);
    setError("");
    try {
      await api(`console/recipes/${recipe.id}/publish`, {
        revision: recipe.revision,
      });
      await load();
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="process-strip">
        <span>
          <b>1</b>
          {t("Ajouter des appareils")}
        </span>
        <span className="process-current">
          <b>2</b>
          {t("Créer un parcours")}
        </span>
        <span>
          <b>3</b>
          {t("Lancer ou planifier")}
        </span>
      </div>
      <div className="section-heading">
        <div>
          <h2>{t("Vos parcours")}</h2>
          <p>
            {t(
              "Préparez les instructions et les étapes, puis publiez une version prête à lancer.",
            )}
          </p>
        </div>
        {canBuild && (
          <button
            className="button button--primary"
            onClick={() => setEditing("new")}
          >
            <Icon name="plus" />
            {t("Créer un parcours")}
          </button>
        )}
      </div>
      {error && <ErrorNotice message={error} />}
      {canBuild && (
        <section className="surface recipe-list" aria-busy={loading}>
          {(loading || loadError) && <div className="recipe-list-status">{loading && <p className="small-copy" role="status">{t("Chargement…")}</p>}{loadError && <><ErrorNotice message={loadError} /><button type="button" className="button button--secondary" disabled={loading || busy} onClick={() => void load(requestedOffset.current)}>{t("Réessayer")}</button></>}</div>}
          {!loading && !loadError && page && !recipes.length && <Empty icon="workflow" title={t("Aucun parcours créé")}>{t("Créez votre premier parcours, puis publiez-le pour le lancer.")}</Empty>}
          <div>{recipes.map((recipe) => (
            <article className="recipe-row" key={recipe.id}>
              <div>
                <h3>{recipe.name}</h3>
                <p>{recipe.instructions}</p>
                <span className="version-tag">
                  {t(recipe.status === "draft" ? "Brouillon" : "Publié")} ·{" "}
                  {t("Révision {n}", { n: recipe.revision })}
                </span>
              </div>
              <div className="row-actions">
                <button
                  className="button button--secondary"
                  disabled={busy || loading}
                  onClick={() => setEditing(recipe)}
                >
                  {t("Modifier les étapes")}
                </button>
                <button
                  className="button button--primary"
                  disabled={busy || loading}
                  onClick={() => void publish(recipe)}
                >
                  {t("Publier")}
                </button>
              </div>
            </article>
          ))}</div>
          {page && <div className="table-footer"><span>{recipes.length ? t("{start}–{end} sur {total}", { start: offset + 1, end: offset + recipes.length, total }) : t("{n} parcours", { n: total })}</span><div className="row-actions"><button type="button" className="button button--secondary" disabled={loading || busy || offset === 0} onClick={() => void load(Math.max(0, offset - 100))}>{t("Précédent")}</button><button type="button" className="button button--secondary" disabled={loading || busy || offset + recipes.length >= total} onClick={() => void load(offset + 100)}>{t("Suivant")}</button></div></div>}
        </section>
      )}
      <div className="section-heading">
        <div>
          <h2>{t("Versions publiées")}</h2>
          <p>
            {t(
              "Une version publiée conserve ses étapes à l’identique pour chaque exécution.",
            )}
          </p>
          {canBuild && <p>{t("Modifiez le brouillon courant, puis publiez une nouvelle version pour appliquer vos changements.")}</p>}
        </div>
      </div>
      {!workflows.length ? (
        <section className="surface">
          <Empty icon="workflow" title={t("Aucun parcours publié")}>
            {t("Créez votre premier parcours, puis publiez-le pour le lancer.")}
          </Empty>
        </section>
      ) : (
        <section className="surface workflow-list">
          {workflows.map((workflow) => (
            <article
              className="workflow-row"
              key={`${workflow.workflow_id}:${workflow.version}`}
            >
              <div className="workflow-symbol">
                <Icon name="workflow" size={26} />
              </div>
              <div className="workflow-copy">
                <div className="title-with-badge">
                  <h3>
                    {workflow.name ||
                      recipes.find(
                        (r) => r.workflow_id === workflow.workflow_id,
                      )?.name ||
                      t(workflowName(workflow.workflow_id))}
                  </h3>
                  <span className="version-tag">
                    {t("Version {n}", { n: workflow.version })}
                  </span>
                </div>
                <p>
                  {workflow.instructions ||
                    recipes.find((r) => r.workflow_id === workflow.workflow_id)
                      ?.instructions ||
                    (workflow.workflow_id === "chrome-wikipedia-football"
                      ? t(
                          "Ouvrir Chrome, rechercher football sur Wikipédia et vérifier le résultat.",
                        )
                      : "")}
                </p>
                <div className="metadata-line">
                  {t("{n} étapes", { n: workflow.steps.length })}
                </div>
                <details className="steps-disclosure">
                  <summary>{t("Consulter les étapes")}</summary>
                  <ol className="workflow-steps">
                    {workflow.steps.map((s) => (
                      <li key={s.id}>
                        <span>{s.id.replace(/-/g, " ")}</span>
                        <code dir="ltr">{s.action}</code>
                      </li>
                    ))}
                  </ol>
                </details>
              </div>
              {(canBuild || canLaunch) && (
                <div className="row-actions">
                  {canBuild && <button className="button button--secondary" disabled={busy} onClick={() => void editPublished(workflow)}>{t("Modifier les étapes")}</button>}
                  {canLaunch && <>
                  <button
                    className="button button--primary"
                    onClick={() => onLaunch(workflow)}
                  >
                    <Icon name="play" size={18} />
                    {t("Lancer")}
                  </button>
                  <button
                    className="button button--secondary"
                    onClick={() => onSchedule(workflow)}
                  >
                    <Icon name="clock" size={18} />
                    {t("Planifier")}
                  </button>
                  </>}
                </div>
              )}
            </article>
          ))}
        </section>
      )}
      {editing && (
        <RecipeEditor
          key={editing === "new" ? "new" : editing.id}
          recipe={editing === "new" ? null : editing}
          templates={workflows}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void load();
            onChanged();
          }}
        />
      )}
    </>
  );
}
