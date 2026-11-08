"use client";

import { useRef, useState, type FormEvent } from "react";
import { api, ApiError } from "../../lib/client-api";
import { useT } from "../../lib/i18n";
import type { Recipe, Step, Workflow } from "../../lib/console-types";
import { duplicateEditorStep, editorActionLabel, freshEditorStep, parseEditorSteps } from "../../lib/workflow-editor";
import { Dialog, ErrorNotice, workflowName } from "./shared";
import { Icon } from "./icons";
import { StepEditor, stepPreview } from "./step-editor";

export function RecipeEditor({ recipe, templates, onClose, onSaved }: {
  recipe: Recipe | null; templates: Workflow[]; onClose: () => void; onSaved: (recipe?: Recipe) => void;
}) {
  const t = useT();
  const [name, setName] = useState(recipe?.name ?? "");
  const [instructions, setInstructions] = useState(recipe?.instructions ?? "");
  const [steps, setSteps] = useState<Step[]>(() => structuredClone(recipe?.definition.steps ?? [freshEditorStep()]));
  const [expanded, setExpanded] = useState<string | null>(steps[0]?.id ?? null);
  const [advanced, setAdvanced] = useState(false);
  const [json, setJson] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<"goal" | "expert">(recipe ? "expert" : "goal");
  const [generatedFrom, setGeneratedFrom] = useState("");
  const [expected, setExpected] = useState("");
  const saving = useRef(false);
  const hasGeneration = !!generatedFrom && generatedFrom === instructions.trim();
  function close() { if (!saving.current) onClose(); }
  async function generate() {
    if (saving.current || instructions.trim().length < 8) return;
    saving.current = true; setBusy(true); setError("");
    try {
      const result = await api<{recipe: {name: string; steps: Step[]}; expected_result: string}>("console/recipes/generate", {instructions: instructions.trim()});
      setName(result.recipe.name); setSteps(result.recipe.steps);
      setJson(JSON.stringify(result.recipe.steps, null, 2)); setAdvanced(false);
      setExpected(result.expected_result); setGeneratedFrom(instructions.trim());
    } catch (failure) { setError(failure instanceof ApiError && failure.code === "chatgpt_required" ? t("Connectez ChatGPT dans Configuration pour préparer cet objectif libre.") : failure instanceof ApiError && failure.code === "unsupported_goal" ? t("Cet objectif dépasse les capacités actuelles. Essayez une recherche Wikipédia, l’ouverture d’une application ou la lecture de la version Android.") : (failure as Error).message); }
    finally { saving.current = false; setBusy(false); }
  }
  function update(step: Step) { setSteps(items => items.map(item => item.id === step.id ? step : item)); }
  function move(index: number, offset: number) {
    setSteps(items => {
      const next = [...items];
      [next[index], next[index + offset]] = [next[index + offset], next[index]];
      return next;
    });
  }
  function toggleAdvanced() {
    if (advanced) {
      try { const parsed = parseEditorSteps(json); setSteps(parsed); setAdvanced(false); setError(""); }
      catch { setError(t("Le JSON des étapes est invalide.")); }
    } else { setJson(JSON.stringify(steps, null, 2)); setAdvanced(true); setError(""); }
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (saving.current) return;
    if (mode === "goal" && !hasGeneration) { await generate(); return; }
    setError("");
    let parsed: Step[];
    try { parsed = parseEditorSteps(advanced ? json : JSON.stringify(steps)); }
    catch { setError(t("Le JSON des étapes est invalide.")); return; }
    saving.current = true; setBusy(true);
    try {
      const saved = await api<Recipe>(recipe ? `console/recipes/${recipe.id}` : "console/recipes", {
        name: name.trim(), instructions: instructions.trim(), steps: parsed,
        recovery_budget: recipe?.definition.recovery_budget ?? 0,
        ...(recipe ? { revision: recipe.revision } : {}),
      }, recipe ? "PATCH" : "POST");
      onSaved(saved);
    } catch (error) {
      setError(error instanceof ApiError && error.status === 409
        ? t("Ce brouillon a changé depuis son ouverture. Vos modifications sont conservées ici. Copiez le JSON avancé avant de fermer, puis rouvrez le parcours à jour.")
        : (error as Error).message);
    } finally { saving.current = false; setBusy(false); }
  }
  return <Dialog wide className="console-dialog--recipe" title={t(recipe ? "Modifier le parcours" : "Créer un parcours")} description={t(recipe ? "Modifiez le brouillon courant, puis publiez une nouvelle version pour appliquer vos changements." : "Décrivez votre objectif. La console prépare les étapes pour vous.")} onClose={close}>
    <form className="dialog-form recipe-editor-form" onSubmit={save} aria-busy={busy}>
      {error && <ErrorNotice message={error} />}
      <fieldset className="recipe-editor-inputs" disabled={busy}>
        <div className="notice notice--info">{t("Le moteur prend en charge Chrome, Wikipédia, l’ouverture d’applications et la lecture de la version Android dans les paramètres.")}</div>
        <div className="button-row"><button type="button" className={`button ${mode === "goal" ? "button--primary" : "button--secondary"}`} aria-pressed={mode === "goal"} onClick={() => {setMode("goal"); setGeneratedFrom("");}}>{t("Décrire mon objectif")}</button><button type="button" className={`button ${mode === "expert" ? "button--primary" : "button--secondary"}`} aria-pressed={mode === "expert"} onClick={() => setMode("expert")}>{t("Réglages avancés")}</button></div>
        {(mode === "expert" || hasGeneration) && <label>{t("Nom du parcours")}<input required maxLength={120} value={name} onChange={event => setName(event.target.value)} placeholder={t("Ex. Recherche Wikipédia")} /></label>}
        <label>{t("Instructions et résultat attendu")}<textarea required maxLength={8000} rows={3} value={instructions} onChange={event => setInstructions(event.target.value)} placeholder={t("Ex. Ouvrir Wikipédia, rechercher football et vérifier le titre de l’article.")} />
          <span>{t(mode === "goal" ? "La génération ne lance aucune action. Vérifiez le résumé avant d’enregistrer, puis testez le parcours sur un appareil." : "Les instructions expliquent l’objectif. Les étapes ci-dessous définissent les actions exécutées.")}</span>
        </label>
        {mode === "goal" && <><button type="button" className="text-button" onClick={() => setInstructions("Ouvrir Wikipédia, rechercher football et vérifier le titre de l’article.")}>{t("Utiliser l’exemple Wikipédia")}</button><button type="button" className="text-button" onClick={() => setInstructions("Ouvre les paramètres du téléphone et donne-moi la version d’Android.")}>{t("Utiliser l’exemple version Android")}</button><p className="small-copy">{t("Les exemples Wikipédia et version Android fonctionnent sans compte externe. Pour un autre objectif, connectez ChatGPT dans Configuration. Les capacités non prises en charge sont signalées.")} <a href="/configuration">{t("Configuration")}</a></p>{hasGeneration && <div className="review-section"><h3>{t("Résultat attendu")}</h3><p>{expected}</p><ol>{steps.map(step => <li key={step.id}>{t(editorActionLabel(step.action))} · <bdi>{stepPreview(step)}</bdi></li>)}</ol><button type="button" className="text-button" onClick={() => setGeneratedFrom("")}>{t("Générer à nouveau")}</button></div>}</>}
        {mode === "expert" && <>
        {!recipe && <label>{t("Partir d’un modèle")}<select defaultValue="" onChange={event => {
          const template = templates.find(item => `${item.workflow_id}:${item.version}` === event.target.value);
          if (template) { const copied = structuredClone(template.steps); setSteps(copied); setJson(JSON.stringify(copied, null, 2)); setExpanded(copied[0]?.id ?? null); }
        }}>
          <option value="">{t("Parcours personnalisé")}</option>
          {templates.map(item => <option key={`${item.workflow_id}:${item.version}`} value={`${item.workflow_id}:${item.version}`}>{item.name || t(workflowName(item.workflow_id))} · v{item.version}</option>)}
        </select></label>}
        <div className="section-heading recipe-steps-heading"><div><h3>{t("Étapes du parcours")}</h3><p>{t("{n} étapes", { n: steps.length })}</p></div>
          <button type="button" className="text-button" onClick={toggleAdvanced}>{t(advanced ? "Éditeur visuel" : "JSON avancé")}</button>
        </div>
        {advanced ? <label>{t("Définition des étapes")}<textarea className="code-editor" dir="ltr" rows={22} value={json} onChange={event => setJson(event.target.value)} spellCheck={false} /></label>
          : <div className="step-editor-list">{steps.map((step, index) => <article className="recipe-step-card" key={step.id}>
            <div className="recipe-step-header">
              <button type="button" className="recipe-step-toggle" aria-expanded={expanded === step.id} aria-controls={`editor-${step.id}`} onClick={() => setExpanded(expanded === step.id ? null : step.id)}>
                <span className="recipe-step-number">{index + 1}</span>
                <span className="recipe-step-summary"><strong>{t(editorActionLabel(step.action))}</strong><span dir="auto">{stepPreview(step)}</span></span>
                <span aria-hidden="true">{expanded === step.id ? "−" : "+"}</span>
              </button>
              <div className="recipe-step-actions">
                <button type="button" className="text-button" disabled={index === 0} aria-label={t("Monter l’étape")} onClick={() => move(index, -1)}>↑</button>
                <button type="button" className="text-button" disabled={index === steps.length - 1} aria-label={t("Descendre l’étape")} onClick={() => move(index, 1)}>↓</button>
                <button type="button" className="text-button" disabled={steps.length >= 14} onClick={() => {
                  const copy = duplicateEditorStep(step); setSteps(items => [...items.slice(0, index + 1), copy, ...items.slice(index + 1)]); setExpanded(copy.id);
                }}>{t("Dupliquer")}</button>
                <button type="button" className="text-button" disabled={steps.length === 1} onClick={() => setSteps(items => items.filter(item => item.id !== step.id))}>{t("Supprimer")}</button>
              </div>
            </div>
            {expanded === step.id && <div className="recipe-step-body" id={`editor-${step.id}`}><StepEditor step={step} onChange={update} /></div>}
          </article>)}
            <button type="button" className="button button--secondary" disabled={steps.length >= 14} onClick={() => {
              const step = freshEditorStep(); setSteps(items => [...items, step]); setExpanded(step.id);
            }}><Icon name="plus" />{t("Ajouter une étape")}</button>
          </div>}
        </>}
      </fieldset>
      <div className="dialog-footer">
        <button type="button" className="button button--secondary" onClick={close} disabled={busy}>{t("Annuler")}</button>
        <button className="button button--primary" disabled={busy || instructions.trim().length < 8}>{t(busy ? "Chargement…" : mode === "goal" && !hasGeneration ? "Préparer mon parcours" : "Enregistrer le brouillon")}</button>
      </div>
    </form>
  </Dialog>;
}
