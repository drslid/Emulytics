"use client";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../../lib/client-api";
import { useT } from "../../lib/i18n";
import type { Page, Recipe, Step, Workflow } from "../../lib/console-types";
import { Dialog, Empty, ErrorNotice, workflowName } from "./shared";
import { Icon } from "./icons";
import {
  editorActions as actions,
  parseEditorSteps,
} from "../../lib/workflow-editor";

function freshStep(action = "open_app"): Step {
  const args: Record<string, unknown> =
    action === "open_app"
      ? { package_name: "com.android.chrome" }
      : action === "open_url"
        ? { url: "https://fr.wikipedia.org/" }
        : action === "press_key"
          ? { keycode: "KEYCODE_ENTER" }
          : action === "type_text"
            ? { text: "", clear: true }
            : action === "ensure_package"
              ? { package: "com.android.chrome" }
              : action === "swipe"
                ? { x1: 500, y1: 1000, x2: 500, y2: 300, duration_ms: 400 }
                : {};
  return {
    id: `step-${crypto.randomUUID().slice(0, 8)}`,
    action,
    args,
    selectors: ["tap", "type_text"].includes(action)
      ? [{ resource_id: "" }]
      : [],
    assert:
      action === "ensure_package"
        ? { type: "package_installed", value: "com.android.chrome" }
        : { type: "package", value: "com.android.chrome" },
    timeout_ms: 30000,
    non_idempotent: false,
    recovery_budget: 0,
  };
}
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
  const [recipes, setRecipes] = useState<Recipe[]>([]),
    [editing, setEditing] = useState<Recipe | "new" | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      const result = await api<Page<Recipe>>("console/recipes?limit=100");
      setRecipes(result.items);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
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
      {canBuild && recipes.length > 0 && (
        <section className="surface recipe-list">
          {recipes.map((recipe) => (
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
                  onClick={() => setEditing(recipe)}
                >
                  {t("Modifier")}
                </button>
                <button
                  className="button button--primary"
                  disabled={busy}
                  onClick={() => void publish(recipe)}
                >
                  {t("Publier")}
                </button>
              </div>
            </article>
          ))}
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
              {canLaunch && (
                <div className="row-actions">
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
                </div>
              )}
            </article>
          ))}
        </section>
      )}
      {editing && (
        <RecipeEditor
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
function RecipeEditor({
  recipe,
  templates,
  onClose,
  onSaved,
}: {
  recipe: Recipe | null;
  templates: Workflow[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useT();
  const [name, setName] = useState(recipe?.name ?? ""),
    [instructions, setInstructions] = useState(recipe?.instructions ?? ""),
    [steps, setSteps] = useState<Step[]>(
      recipe?.definition.steps ?? [freshStep()],
    ),
    [advanced, setAdvanced] = useState(false),
    [json, setJson] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  function update(index: number, patch: Partial<Step>) {
    setSteps((items) =>
      items.map((s, i) => (i === index ? { ...s, ...patch } : s)),
    );
  }
  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      let parsed: Step[];
      try {
        parsed = parseEditorSteps(advanced ? json : JSON.stringify(steps));
      } catch {
        setError(t("Le JSON des étapes est invalide."));
        return;
      }
      await api(
        recipe ? `console/recipes/${recipe.id}` : "console/recipes",
        {
          name: name.trim(),
          instructions: instructions.trim(),
          steps: parsed,
          recovery_budget: recipe?.definition.recovery_budget ?? 0,
          ...(recipe ? { revision: recipe.revision } : {}),
        },
        recipe ? "PATCH" : "POST",
      );
      onSaved();
    } catch (e) {
      setError(
        e instanceof SyntaxError
          ? t("Le JSON des étapes est invalide.")
          : (e as Error).message,
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      wide
      title={t(recipe ? "Modifier le parcours" : "Créer un parcours")}
      description={t(
        "Décrivez le résultat attendu, puis préparez les étapes exécutables.",
      )}
      onClose={onClose}
    >
      <form className="dialog-form" onSubmit={save}>
        {error && <ErrorNotice message={error} />}
        <div className="notice notice--info">
          {t(
            "Le moteur actif prend en charge Chrome et les pages HTTPS de Wikipédia.",
          )}
        </div>
        <label>
          {t("Nom du parcours")}
          <input
            required
            maxLength={120}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("Ex. Recherche Wikipédia")}
          />
        </label>
        <label>
          {t("Instructions et résultat attendu")}
          <textarea
            required
            maxLength={8000}
            rows={3}
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            placeholder={t(
              "Ex. Ouvrir Wikipédia, rechercher football et vérifier le titre de l’article.",
            )}
          />
          <span>
            {t(
              "Les instructions expliquent l’objectif. Les étapes ci-dessous définissent les actions exécutées.",
            )}
          </span>
        </label>
        {!recipe && (
          <label>
            {t("Partir d’un modèle")}
            <select
              defaultValue=""
              onChange={(e) => {
                const template = templates.find(
                  (w) => `${w.workflow_id}:${w.version}` === e.target.value,
                );
                if (template) {
                  setSteps(structuredClone(template.steps));
                  setJson(JSON.stringify(template.steps, null, 2));
                }
              }}
            >
              <option value="">{t("Parcours personnalisé")}</option>
              {templates.map((w) => (
                <option
                  key={`${w.workflow_id}:${w.version}`}
                  value={`${w.workflow_id}:${w.version}`}
                >
                  {w.name || t(workflowName(w.workflow_id))} · v{w.version}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="section-heading">
          <h3>{t("Étapes du parcours")}</h3>
          <button
            type="button"
            className="text-button"
            onClick={() => {
              if (advanced) {
                try {
                  const parsed = parseEditorSteps(json);
                  setSteps(parsed);
                  setAdvanced(false);
                  setError("");
                } catch {
                  setError(t("Le JSON des étapes est invalide."));
                }
              } else {
                setJson(JSON.stringify(steps, null, 2));
                setAdvanced(true);
              }
            }}
          >
            {t(advanced ? "Éditeur visuel" : "JSON avancé")}
          </button>
        </div>
        {advanced ? (
          <label>
            {t("Définition des étapes")}
            <textarea
              className="code-editor"
              dir="ltr"
              rows={20}
              value={json}
              onChange={(e) => setJson(e.target.value)}
            />
          </label>
        ) : (
          <div className="step-editor-list">
            {steps.map((step, index) => (
              <section className="step-editor" key={step.id}>
                <div className="step-toolbar">
                  <strong>{t("Étape {n}", { n: index + 1 })}</strong>
                  <div className="row-actions">
                    <button
                      type="button"
                      className="text-button"
                      disabled={index === 0}
                      aria-label={t("Monter l’étape")}
                      onClick={() =>
                        setSteps((items) => {
                          const result = [...items];
                          [result[index - 1], result[index]] = [
                            result[index],
                            result[index - 1],
                          ];
                          return result;
                        })
                      }
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      className="text-button"
                      disabled={index === steps.length - 1}
                      aria-label={t("Descendre l’étape")}
                      onClick={() =>
                        setSteps((items) => {
                          const result = [...items];
                          [result[index + 1], result[index]] = [
                            result[index],
                            result[index + 1],
                          ];
                          return result;
                        })
                      }
                    >
                      ↓
                    </button>
                    <button
                      type="button"
                      className="text-button"
                      disabled={steps.length === 1}
                      onClick={() =>
                        setSteps((items) => items.filter((_, i) => i !== index))
                      }
                    >
                      {t("Supprimer")}
                    </button>
                  </div>
                </div>
                <label>
                  {t("Action")}
                  <select
                    value={step.action}
                    onChange={(e) =>
                      update(index, {
                        ...freshStep(e.target.value),
                        id: step.id,
                      })
                    }
                  >
                    {Object.entries(actions).map(([value, label]) => (
                      <option key={value} value={value}>
                        {t(label)}
                      </option>
                    ))}
                  </select>
                </label>
                {[
                  "open_app",
                  "ensure_package",
                  "open_url",
                  "type_text",
                  "press_key",
                ].includes(step.action) &&
                  (() => {
                    const key =
                      step.action === "open_app"
                        ? "package_name"
                        : step.action === "ensure_package"
                          ? "package"
                          : step.action === "open_url"
                            ? "url"
                            : step.action === "type_text"
                              ? "text"
                              : "keycode";
                    return (
                      <label>
                        {t(
                          step.action === "open_url"
                            ? "Adresse web"
                            : step.action === "type_text"
                              ? "Texte à saisir"
                              : step.action === "press_key"
                                ? "Touche Android"
                                : "Identifiant de l’application",
                        )}
                        <input
                          required
                          dir="ltr"
                          value={String(step.args?.[key] ?? "")}
                          onChange={(e) =>
                            update(index, {
                              args: {
                                ...step.args,
                                [key]:
                                  key === "text"
                                    ? e.target.value
                                    : e.target.value.trimStart(),
                              },
                            })
                          }
                        />
                      </label>
                    );
                  })()}
                {["tap", "type_text"].includes(step.action) && (
                  <label>
                    {t("Élément ciblé (resource-id)")}
                    <input
                      dir="ltr"
                      value={String(step.selectors?.[0]?.resource_id ?? "")}
                      onChange={(e) =>
                        update(index, {
                          selectors: [{ resource_id: e.target.value.trim() }],
                        })
                      }
                    />
                    <span>
                      {t(
                        "Les sélecteurs par texte ou description sont disponibles dans JSON avancé.",
                      )}
                    </span>
                  </label>
                )}
                {step.action === "swipe" && (
                  <p>
                    {t("Réglez les coordonnées et la durée dans JSON avancé.")}
                  </p>
                )}
                <label>
                  {t("Vérification après l’action")}
                  <select
                    value={String(step.assert?.type ?? "package")}
                    onChange={(e) =>
                      update(index, {
                        assert:
                          e.target.value === "ui"
                            ? { type: "ui", selector: { text: "" } }
                            : e.target.value === "url"
                              ? { type: "url", host: "fr.wikipedia.org" }
                              : {
                                  type: e.target.value,
                                  value: "com.android.chrome",
                                },
                      })
                    }
                  >
                    <option value="package">
                      {t("Application au premier plan")}
                    </option>
                    <option value="package_installed">
                      {t("Application installée")}
                    </option>
                    <option value="ui">{t("Texte visible")}</option>
                    <option value="url">{t("Domaine de la page")}</option>
                    {step.assert?.type === "all" && (
                      <option value="all">
                        {t("Plusieurs vérifications (modèle)")}
                      </option>
                    )}
                  </select>
                </label>
                {step.assert?.type !== "all" && (
                  <label>
                    {t("Valeur attendue")}
                    <input
                      required
                      dir="ltr"
                      value={String(
                        step.assert?.type === "ui"
                          ? ((step.assert.selector as Record<string, unknown>)
                              ?.text ?? "")
                          : step.assert?.type === "url"
                            ? (step.assert.host ?? "")
                            : (step.assert?.value ?? ""),
                      )}
                      onChange={(e) =>
                        update(index, {
                          assert:
                            step.assert?.type === "ui"
                              ? {
                                  type: "ui",
                                  selector: { text: e.target.value },
                                }
                              : step.assert?.type === "url"
                                ? { type: "url", host: e.target.value.trim() }
                                : {
                                    ...step.assert,
                                    value: e.target.value.trim(),
                                  },
                        })
                      }
                    />
                  </label>
                )}
              </section>
            ))}
            <button
              type="button"
              className="button button--secondary"
              disabled={steps.length >= 14}
              onClick={() => setSteps((items) => [...items, freshStep()])}
            >
              <Icon name="plus" />
              {t("Ajouter une étape")}
            </button>
          </div>
        )}
        <div className="dialog-footer">
          <button
            type="button"
            className="button button--secondary"
            onClick={onClose}
            disabled={busy}
          >
            {t("Annuler")}
          </button>
          <button className="button button--primary" disabled={busy}>
            {t(busy ? "Enregistrement…" : "Enregistrer le brouillon")}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
