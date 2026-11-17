"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { api, ApiError } from "../../lib/client-api";
import type { JourneyModels, JourneyProviderId, NaturalCard, Recipe, Workflow } from "../../lib/console-types";
import { useT } from "../../lib/i18n";
import { MAX_CARD_CONTEXT, MAX_CARD_TEXT, MAX_RECIPE_CARDS, normalizeRecipeCards, recipeCardTextLength, recipeCardSlots } from "../../lib/recipe-cards";
import type { RecipeBody } from "../../lib/run-authoring";
import { freshEditorStep } from "../../lib/workflow-editor";
import { Icon } from "./icons";
import { publishEditorRecipe, RecipeEditorFrame, saveEditorRecipe, type RecipeEditorSession } from "./recipe-editor-shared";
import { ErrorNotice, workflowName } from "./shared";
import { CompiledStepPreview } from "./step-editor";
import { TechnicalRecipeEditor } from "./technical-recipe-editor";

const providerNames = { openai: "OpenAI", ollama: "Ollama", deepseek: "DeepSeek" };
type Preview = { body: RecipeBody; expected?: string };
type ProposedCard = Omit<NaturalCard, "id">;
type Operation = "preparing" | "suggesting" | "saving";
const freshCard = (proposal?: ProposedCard): NaturalCard => ({
  id: crypto.randomUUID(), instruction: proposal?.instruction ?? "", verification: proposal?.verification ?? null
});

function savedBody(recipe?: Recipe | null, source?: Workflow): RecipeBody | null {
  if (recipe?.cards?.length) return {
    name: recipe.name, instructions: recipe.instructions, steps: recipe.definition.steps,
    recovery_budget: recipe.definition.recovery_budget, cards: recipe.cards
  };
  if (source?.cards?.length) return {
    name: source.name ?? source.workflow_id, instructions: source.instructions ?? "",
    steps: source.steps, recovery_budget: source.recovery_budget, cards: source.cards
  };
  return null;
}

export function CardRecipeEditor(props: RecipeEditorSession) {
  const { recipe, inline, run, runState, onClose, onSaved } = props;
  const t = useT();
  const idPrefix = useId();
  const source = run?.source;
  const [initial] = useState(() => savedBody(recipe, source));
  const [cards, setCards] = useState<NaturalCard[]>(() => initial?.cards ?? [freshCard()]);
  const [name, setName] = useState(() => recipe?.name ?? (source ? source.name || t(workflowName(source.workflow_id)) : ""));
  const [preview, setPreview] = useState<Preview | null>(() => initial ? { body: initial } : null);
  const [technical, setTechnical] = useState<RecipeBody | null>(null);
  const [discovery, setDiscovery] = useState<JourneyModels | "failed" | null>(null);
  const [attempt, retryProviders] = useState(0);
  const [providerOverride, setProviderOverride] = useState<JourneyProviderId>();
  const [operation, setOperation] = useState<Operation | null>(null);
  const [error, setError] = useState("");
  const [cardError, setCardError] = useState<{ id: string; message: string } | null>(null);
  const [savedNotice, setSavedNotice] = useState("");
  const [prompt, setPrompt] = useState("");
  const [suggestions, setSuggestions] = useState<ProposedCard[] | null>(null);
  const [suggestionError, setSuggestionError] = useState("");
  const inFlight = useRef(false);
  const nextFocus = useRef<string | null>(null);
  const help = useRef<HTMLDetailsElement>(null);
  const models = discovery === "failed" ? null : discovery;
  const provider = providerOverride ?? models?.active_provider;
  const payload = normalizeRecipeCards(cards);
  const tooLong = recipeCardTextLength(payload) > MAX_CARD_CONTEXT;
  const ready = !tooLong && payload.every(card => card.instruction);
  const remaining = MAX_RECIPE_CARDS - recipeCardSlots(cards).length;

  useEffect(() => {
    let active = true;
    setDiscovery(null);
    void api<JourneyModels>("console/recipes/providers").then(value => {
      if (active) setDiscovery(typeof value?.active_provider === "string" && Object.hasOwn(providerNames, value.active_provider) ? value : "failed");
    }).catch(() => { if (active) setDiscovery("failed"); });
    return () => { active = false; };
  }, [attempt]);

  useEffect(() => {
    if (operation || !nextFocus.current) return;
    document.getElementById(nextFocus.current)?.focus();
    nextFocus.current = null;
  }, [cards, operation]);

  const inputId = (id: string) => `${idPrefix}-instruction-${id}`;
  function close() { if (!inFlight.current) onClose(); }
  function changeCards(next: NaturalCard[]) {
    setCards(next);
    setPreview(null);
    setCardError(null);
    setError("");
    setSavedNotice("");
  }
  function changeCard(id: string, change: Partial<Pick<NaturalCard, "instruction" | "verification">>) {
    changeCards(cards.map(card => card.id === id ? { ...card, ...change } : card));
  }
  function moveCard(index: number, offset: number) {
    const updated = [...cards];
    [updated[index], updated[index + offset]] = [updated[index + offset], updated[index]];
    changeCards(updated);
  }
  function addCards(proposed?: ProposedCard[]) {
    const retained = proposed ? recipeCardSlots(cards) : cards;
    if (retained.length + (proposed?.length ?? 1) > MAX_RECIPE_CARDS) return;
    const added = proposed ? proposed.map(freshCard) : [freshCard()];
    if (!added.length) return;
    nextFocus.current = inputId(added[0].id);
    changeCards([...retained, ...added]);
    if (proposed) {
      setPrompt("");
      setSuggestions(null);
      if (help.current) help.current.open = false;
    }
  }
  function openTechnical() {
    const base = preview?.body ?? initial;
    setTechnical({
      name, instructions: base?.instructions ?? payload.map(card => card.instruction).join("\n").slice(0, 8000),
      steps: base?.steps ?? [freshEditorStep()], recovery_budget: base?.recovery_budget ?? 0, cards: base?.cards ?? null
    });
  }

  function providerError(failure: unknown, fallback: string) {
    if (!(failure instanceof ApiError)) return t(fallback);
    if (failure.code === "chatgpt_required") return t("Connectez OpenAI dans Configuration pour préparer cet objectif libre.");
    if (failure.code === "provider_unconfigured" || failure.status === 503 && provider && provider !== "openai") {
      return t("{provider} est indisponible. Vérifiez sa configuration puis réessayez.", { provider: provider ? providerNames[provider] : "" });
    }
    if (failure.code === "provider_auth_failed") return t("Le fournisseur a refusé les identifiants.");
    if (failure.code === "provider_model_unavailable") return t("Le modèle configuré est introuvable.");
    return failure.status === 422 ? t(fallback) : failure.message;
  }

  async function perform(kind: Operation, action: () => Promise<void>, onError: (error: unknown) => void) {
    if (inFlight.current) return;
    inFlight.current = true;
    setOperation(kind);
    try { await action(); }
    catch (failure) { onError(failure); }
    finally { inFlight.current = false; setOperation(null); }
  }

  async function prepare() {
    if (!ready) return;
    setError("");
    setCardError(null);
    await perform("preparing", async () => {
      const result = await api<{ recipe: Omit<RecipeBody, "cards">; expected_result: string }>("console/recipes/prepare-cards", {
        cards: payload,
        ...(models && provider ? { provider } : { local_only: true }),
        ...(run?.deviceId ? { device_id: run.deviceId } : {}),
        ...(name.trim() ? { name: name.trim() } : {})
      });
      const compiled = result.recipe;
      setName(name.trim() || compiled.name);
      setPreview({ body: {
        name: compiled.name, instructions: compiled.instructions, steps: compiled.steps,
        recovery_budget: compiled.recovery_budget, cards: payload
      }, expected: result.expected_result });
    }, failure => {
      if (failure instanceof ApiError && failure.card && cards.some(card => card.id === failure.card?.id)) {
        nextFocus.current = inputId(failure.card.id);
        setCardError({ id: failure.card.id, message: t(failure.card.message || "Précisez l’instruction ou le résultat à vérifier.") });
      } else if (failure instanceof ApiError && failure.code === "provider_discovery_required") {
        setError(t("Chargez les fournisseurs IA, puis réessayez de préparer ces instructions."));
      } else {
        setError(providerError(failure, "Impossible de préparer les étapes. Précisez les instructions ou ouvrez l’éditeur technique."));
      }
    });
  }

  async function suggest() {
    if (!provider || !models || prompt.trim().length < 8) return;
    setSuggestionError("");
    setSuggestions(null);
    await perform("suggesting", async () => {
      const result = await api<{ cards: ProposedCard[] }>("console/recipes/suggest-cards", { instructions: prompt.trim(), provider });
      setSuggestions(result.cards);
    }, failure => setSuggestionError(providerError(failure, "Impossible de proposer des étapes. Précisez le résultat souhaité.")));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (inFlight.current) return;
    if (!preview) { await prepare(); return; }
    if (!name.trim()) return;
    const publish = (event.nativeEvent as SubmitEvent).submitter?.getAttribute("value") === "publish";
    setError("");
    setSavedNotice("");
    await perform("saving", async () => {
      const saved = await saveEditorRecipe({ ...preview.body, name: name.trim() }, recipe, recipe ? undefined : runState);
      if (!run) onSaved?.(saved);
      else if (publish) {
        const workflow = await publishEditorRecipe(saved);
        setSavedNotice(t("Parcours publié."));
        run.onPrepared(workflow);
      } else setSavedNotice(t("Brouillon enregistré."));
    }, failure => setError(failure instanceof ApiError && failure.status === 409
      ? t("Ce brouillon a changé depuis son ouverture. Rouvrez le parcours à jour après avoir copié vos instructions.")
      : (failure as Error).message));
  }

  if (technical) return <TechnicalRecipeEditor {...props} seed={technical} onBack={() => setTechnical(null)} />;
  const fullPage = run || inline;
  return <RecipeEditorFrame recipe={recipe} inline={inline} run={run} onClose={close}>
    <form className={`dialog-form card-recipe-form${fullPage ? " card-recipe-full" : ""}`} onSubmit={submit} aria-busy={!!operation}>
      <fieldset className="recipe-editor-inputs" disabled={!!operation}>
        {source && run?.sourceRunId && <p className="small-copy">{t("Copie de l’exécution {id} · parcours v{version}", { id: run.sourceRunId.slice(0, 8), version: source.version })}</p>}
        <ol className="recipe-card-list">
          {cards.map((card, index) => {
            const clarification = cardError?.id === card.id ? cardError.message : undefined;
            const errorId = `${inputId(card.id)}-error`;
            const verifyId = `${inputId(card.id)}-verification`;
            return <li key={card.id} className="surface recipe-card-input">
              <div className="recipe-card-top">
                <span className="recipe-step-number" aria-hidden="true">{index + 1}</span>
                <label htmlFor={inputId(card.id)}>{t("Instruction")}</label>
                {cards.length > 1 && <div className="recipe-card-actions">
                  <button type="button" className="text-button" aria-label={t("Monter l’étape")} disabled={index === 0} onClick={() => moveCard(index, -1)}>↑</button>
                  <button type="button" className="text-button" aria-label={t("Descendre l’étape")} disabled={index === cards.length - 1} onClick={() => moveCard(index, 1)}>↓</button>
                  <button type="button" className="text-button" aria-label={t("Supprimer l’étape {n}", { n: index + 1 })} onClick={() => {
                    nextFocus.current = inputId((cards[index + 1] ?? cards[index - 1]).id);
                    changeCards(cards.filter(item => item.id !== card.id));
                  }}><Icon name="close" size={16} /></button>
                </div>}
              </div>
              <textarea id={inputId(card.id)} dir="auto" value={card.instruction} rows={2} maxLength={MAX_CARD_TEXT}
                placeholder={index === 0 ? t("Ex. Lire la version Android") : undefined}
                aria-invalid={!!clarification} aria-describedby={clarification ? errorId : undefined}
                onChange={event => changeCard(card.id, { instruction: event.target.value })} />
              {card.verification !== null && card.verification !== undefined ? <div className="recipe-card-verification">
                <label>{t("Vérification (facultative)")}
                  <textarea id={verifyId} dir="auto" rows={2} maxLength={MAX_CARD_TEXT} value={card.verification}
                    onChange={event => changeCard(card.id, { verification: event.target.value })} />
                </label>
                <button type="button" className="text-button" onClick={() => {
                  nextFocus.current = inputId(card.id);
                  changeCard(card.id, { verification: null });
                }}>{t("Retirer la vérification")}</button>
              </div> : <button type="button" className="text-button" onClick={() => {
                nextFocus.current = verifyId;
                changeCard(card.id, { verification: "" });
              }}><Icon name="plus" size={16} />{t("Ajouter une vérification")}</button>}
              {clarification && <div id={errorId}><ErrorNotice message={clarification} /></div>}
            </li>;
          })}
        </ol>
        <div className="recipe-card-toolbar">
          <button type="button" className="button button--secondary" disabled={cards.length >= MAX_RECIPE_CARDS} onClick={() => addCards()}>
            <Icon name="plus" size={16} />{t("Ajouter une étape")}
          </button>
          <button type="button" className="text-button" onClick={openTechnical}>{t("Éditeur technique")}</button>
        </div>
        {tooLong && <ErrorNotice message={t("Raccourcissez les instructions et vérifications avant de préparer le parcours.")} />}
        {models && provider ? <details className="recipe-card-options">
          <summary>{t("Fournisseur pour les objectifs libres")} · <bdi>{providerNames[provider]}</bdi></summary>
          <label>{t("Fournisseur pour les objectifs libres")}
            <select value={provider} onChange={event => {
              setProviderOverride(event.target.value as JourneyProviderId);
              setPreview(null);
              setSuggestions(null);
              setSavedNotice("");
              setError("");
              setCardError(null);
              setSuggestionError("");
            }}>
              <option value="openai">OpenAI</option>
              {(models.ollama || provider === "ollama") && <option value="ollama">Ollama · {models.ollama ?? t("Non configuré")}</option>}
              {(models.deepseek || provider === "deepseek") && <option value="deepseek">DeepSeek · {models.deepseek ?? t("Non configuré")}</option>}
            </select>
          </label>
        </details> : discovery === "failed" ? <div className="recipe-provider-error">
          <ErrorNotice message={t("Impossible de charger les fournisseurs IA.")} />
          <button type="button" className="text-button" onClick={() => retryProviders(value => value + 1)}>{t("Réessayer")}</button>
        </div> : <p className="small-copy" role="status">{t("Chargement…")}</p>}
        {provider === "deepseek" && <p className="small-copy">{t("Les objectifs libres sont envoyés à DeepSeek.")}</p>}
        <details ref={help} className="recipe-card-options">
          <summary>{t("M’aider à créer les étapes")}</summary>
          <label>{t("Décrivez le résultat souhaité")}
            <textarea dir="auto" rows={3} maxLength={8000} value={prompt} onChange={event => {
              setPrompt(event.target.value);
              setSuggestions(null);
              setSuggestionError("");
            }} />
          </label>
          <button type="button" className="button button--secondary" disabled={!models || !provider || prompt.trim().length < 8}
            onClick={() => void suggest()}>{t(operation === "suggesting" ? "Chargement…" : "Proposer des étapes")}</button>
          {suggestionError && <ErrorNotice message={suggestionError} />}
          {suggestions && <div className="review-section" aria-live="polite">
            <ol>{suggestions.map((item, index) => <li key={index}>
              <span dir="auto">{item.instruction}</span>
              {item.verification && <p>{t("Vérification")} · <bdi>{item.verification}</bdi></p>}
            </li>)}</ol>
            {suggestions.length > remaining && <p>{t("Libérez des étapes avant d’ajouter ces suggestions.")}</p>}
            <button type="button" className="button button--secondary" disabled={!suggestions.length || suggestions.length > remaining}
              onClick={() => addCards(suggestions)}>{t("Ajouter les étapes proposées")}</button>
          </div>}
        </details>
        {preview && <section className="surface recipe-card-preview" aria-live="polite">
          <h3>{t("Étapes préparées")}</h3>
          <label>{t(run ? "Nom du run" : "Nom du parcours")}
            <input required maxLength={120} value={name} onChange={event => { setName(event.target.value); setSavedNotice(""); }} />
          </label>
          {preview.expected && <div><strong>{t("Résultat attendu")}</strong><p dir="auto">{t(preview.expected)}</p></div>}
          <ol>{preview.body.steps.map(step => <li key={step.id}><CompiledStepPreview step={step} /></li>)}</ol>
        </section>}
      </fieldset>
      {error && <ErrorNotice message={error} />}
      <div className="dialog-footer">
        {savedNotice && <p className="run-authoring-saved" role="status">{savedNotice}</p>}
        <button type="button" className="button button--secondary" disabled={!!operation} onClick={close}>{t("Annuler")}</button>
        {!preview ? <button type="submit" className="button button--primary" disabled={!!operation || !ready}>
          {t(operation === "preparing" ? "Chargement…" : "Préparer le parcours")}
        </button> : <>
          <button type="submit" className={`button ${run ? "button--secondary" : "button--primary"}`} disabled={!!operation || !name.trim()}>
            {t(operation === "saving" && !run ? "Chargement…" : "Enregistrer le brouillon")}
          </button>
          {run && <button type="submit" value="publish" className="button button--primary" disabled={!!operation || !name.trim()}>
            {t(operation === "saving" ? "Chargement…" : "Publier et préparer le lancement")}
          </button>}
        </>}
      </div>
    </form>
  </RecipeEditorFrame>;
}
