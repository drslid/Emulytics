"use client";

import { useRef, useState, type FormEvent } from "react";
import { ApiError } from "../../lib/client-api";
import type { Step } from "../../lib/console-types";
import { useT } from "../../lib/i18n";
import type { RecipeBody } from "../../lib/run-authoring";
import { duplicateEditorStep, editorActionLabel, freshEditorStep, parseEditorSteps } from "../../lib/workflow-editor";
import { Icon } from "./icons";
import { publishEditorRecipe, RecipeEditorFrame, saveEditorRecipe, type RecipeEditorSession } from "./recipe-editor-shared";
import { ErrorNotice, workflowName } from "./shared";
import { StepEditor, stepPreview } from "./step-editor";

export function TechnicalRecipeEditor({ recipe, templates, onClose, onSaved, run, inline, runState, seed, onBack }:
  RecipeEditorSession & { seed?: RecipeBody; onBack?: () => void }) {
  const t = useT();
  const source = run?.source;
  const [name, setName] = useState(() => seed?.name ?? recipe?.name ?? (source ? source.name || t(workflowName(source.workflow_id)) : ""));
  const [instructions, setInstructions] = useState(seed?.instructions ?? recipe?.instructions ?? source?.instructions ?? "");
  const [original] = useState<Step[]>(() => structuredClone(seed?.steps ?? recipe?.definition.steps ?? source?.steps ?? [freshEditorStep()]));
  const [steps, setSteps] = useState(original);
  const [expanded, setExpanded] = useState<string | null>(steps[0]?.id ?? null);
  const [advanced, setAdvanced] = useState(false);
  const [json, setJson] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [savedNotice, setSavedNotice] = useState("");
  const [savedManual, setSavedManual] = useState(false);
  const saving = useRef(false);
  const linkedCards = seed ? seed.cards : recipe?.cards ?? source?.cards;
  function close() { if (!saving.current) onClose(); }
  function update(step: Step) { setSavedNotice(""); setSteps(items => items.map(item => item.id === step.id ? step : item)); }
  function move(index: number, offset: number) {
    setSavedNotice("");
    setSteps(items => {
      const next = [...items];
      [next[index], next[index + offset]] = [next[index + offset], next[index]];
      return next;
    });
  }
  function insertStep(index: number, previous?: Step) {
    const step = previous ? duplicateEditorStep(previous) : freshEditorStep();
    setSavedNotice("");
    setSteps(items => [...items.slice(0, index), step, ...items.slice(index)]);
    setExpanded(step.id);
  }

  function toggleAdvanced() {
    if (advanced) {
      try { setSteps(parseEditorSteps(json)); setAdvanced(false); setError(""); }
      catch { setError(t("Le JSON des étapes est invalide.")); }
    } else { setJson(JSON.stringify(steps, null, 2)); setAdvanced(true); setError(""); }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (saving.current) return;
    setError("");
    setSavedNotice("");
    const prepare = (event.nativeEvent as SubmitEvent).submitter?.getAttribute("value") === "prepare";
    let parsed: Step[];
    try { parsed = parseEditorSteps(advanced ? json : JSON.stringify(steps)); }
    catch { setError(t("Le JSON des étapes est invalide.")); return; }
    saving.current = true;
    setBusy(true);
    const cards = linkedCards && JSON.stringify(parsed) === JSON.stringify(original) ? linkedCards : null;
    try {
      const saved = await saveEditorRecipe({
        name: name.trim(), instructions: instructions.trim(), steps: parsed, cards,
        recovery_budget: seed?.recovery_budget ?? recipe?.definition.recovery_budget ?? source?.recovery_budget ?? 0
      }, recipe, recipe ? undefined : runState);
      if (!run) onSaved?.(saved);
      else if (prepare) {
        const workflow = await publishEditorRecipe(saved);
        setSavedNotice(t("Parcours publié."));
        run.onPrepared(workflow);
      } else {
        if (!cards) setSavedManual(true);
        setSavedNotice(t("Brouillon enregistré."));
      }
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 409
        ? t("Ce brouillon a changé depuis son ouverture. Vos modifications sont conservées ici. Copiez le JSON avancé avant de fermer, puis rouvrez le parcours à jour.")
        : (failure as Error).message);
    } finally { saving.current = false; setBusy(false); }
  }

  return <RecipeEditorFrame recipe={recipe} inline={inline} run={run} onClose={close}>
    <form className={`dialog-form recipe-editor-form${run ? " run-authoring-form" : ""}`} onSubmit={save} aria-busy={busy}
      onChange={() => { if (savedNotice) setSavedNotice(""); }}>
      {error && <ErrorNotice message={error} />}
      <fieldset className="recipe-editor-inputs" disabled={busy}>
        <div className="recipe-editor-basics">
          {run && <h2>{t("Informations de base")}</h2>}
          {onBack && !savedManual && <button type="button" className="text-button recipe-return" onClick={onBack}>{t("Retour aux instructions")}</button>}
          <label>{t(run ? "Nom du run" : "Nom du parcours")}<input required maxLength={120} value={name} onChange={event => setName(event.target.value)} placeholder={t("Ex. Recherche Wikipédia")} /></label>
          <label>{t("Description (facultative)")}<textarea maxLength={8000} rows={3} value={instructions} onChange={event => setInstructions(event.target.value)} /></label>
          {run && <div className="run-authoring-targets">
            <h3><Icon name="phone" size={17} />{t("Appareils Android")}</h3>
            <p>{t("Vous choisirez les appareils et le parallélisme avant de confirmer le lancement.")}</p>
            {source && run.sourceRunId && <p>{t("Copie de l’exécution {id} · parcours v{version}", { id: run.sourceRunId.slice(0, 8), version: source.version })}</p>}
          </div>}
        </div>
        <section className="recipe-editor-steps">
          {!recipe && !source && <label>{t("Partir d’un modèle")}<select defaultValue="" onChange={event => {
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
            : <div className="step-editor-list">
              {steps.map((step, index) => <article className="recipe-step-card" key={step.id}>
                <div className="recipe-step-header">
                  <button type="button" className="recipe-step-toggle" aria-expanded={expanded === step.id} aria-controls={`editor-${step.id}`} onClick={() => setExpanded(expanded === step.id ? null : step.id)}>
                    <span className="recipe-step-number">{index + 1}</span>
                    <span className="recipe-step-summary"><strong>{t(editorActionLabel(step.action))}</strong><span dir="auto">{stepPreview(step)}</span></span>
                    <span aria-hidden="true">{expanded === step.id ? "−" : "+"}</span>
                  </button>
                  <div className="recipe-step-actions">
                    <button type="button" className="text-button" disabled={index === 0} aria-label={t("Monter l’étape")} onClick={() => move(index, -1)}>↑</button>
                    <button type="button" className="text-button" disabled={index === steps.length - 1} aria-label={t("Descendre l’étape")} onClick={() => move(index, 1)}>↓</button>
                    {run && <button type="button" className="text-button" disabled={steps.length >= 14} aria-label={t("Insérer après l’étape {n}", { n: index + 1 })} title={t("Insérer après l’étape {n}", { n: index + 1 })} onClick={() => insertStep(index + 1)}><Icon name="plus" size={15} /></button>}
                    <button type="button" className="text-button" disabled={steps.length >= 14} onClick={() => insertStep(index + 1, step)}>{t("Dupliquer")}</button>
                    <button type="button" className="text-button" disabled={steps.length === 1} onClick={() => {
                      setSavedNotice(""); setSteps(items => items.filter(item => item.id !== step.id));
                    }}>{t("Supprimer")}</button>
                  </div>
                </div>
                {expanded === step.id && <div className="recipe-step-body" id={`editor-${step.id}`}><StepEditor step={step} onChange={update} /></div>}
              </article>)}
              <button type="button" className="button button--secondary" disabled={steps.length >= 14} onClick={() => insertStep(steps.length)}><Icon name="plus" />{t("Ajouter une étape")}</button>
            </div>}
        </section>
      </fieldset>
      <div className="dialog-footer">
        {run && savedNotice && <p className="run-authoring-saved" role="status">{savedNotice}</p>}
        <button type="button" className="button button--secondary" onClick={close} disabled={busy}>{t("Annuler")}</button>
        {run ? <>
          <button className="button button--secondary" type="submit" value="draft" disabled={busy || !name.trim()}>{t("Enregistrer le brouillon")}</button>
          <button className="button button--primary" type="submit" value="prepare" disabled={busy || !name.trim()}>{t(busy ? "Chargement…" : "Publier et préparer le lancement")}</button>
        </> : <button type="submit" className="button button--primary" disabled={busy || !name.trim()}>{t(busy ? "Chargement…" : "Enregistrer le brouillon")}</button>}
      </div>
    </form>
  </RecipeEditorFrame>;
}
