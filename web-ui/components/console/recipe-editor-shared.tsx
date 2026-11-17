"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { api } from "../../lib/client-api";
import type { Recipe, Workflow } from "../../lib/console-types";
import { useT } from "../../lib/i18n";
import { saveRunRecipe, type RecipeBody, type RunRecipeState } from "../../lib/run-authoring";
import { Dialog } from "./shared";

export type RecipeEditorProps = {
  recipe?: Recipe | null;
  onClose: () => void;
  onSaved?: (recipe?: Recipe) => void;
  run?: { source?: Workflow; sourceRunId?: string; deviceId?: string; onPrepared: (workflow: Workflow) => void };
  inline?: boolean;
};

export async function saveEditorRecipe(body: RecipeBody, recipe?: Recipe | null, runState?: RunRecipeState) {
  if (runState) return saveRunRecipe(body, runState, api<Recipe>);
  return api<Recipe>(recipe ? `console/recipes/${recipe.id}` : "console/recipes", {
    ...body, ...(recipe ? { revision: recipe.revision, accept_replay: true } : {})
  }, recipe ? "PATCH" : "POST");
}

export async function publishEditorRecipe(recipe: Recipe) {
  const published = await api<Recipe>(`console/recipes/${recipe.id}/publish`, { revision: recipe.revision });
  return api<Workflow>(`workflows/${encodeURIComponent(published.workflow_id)}/versions/${published.latest_version}`);
}

export function RecipeEditorFrame({ recipe, inline, run, onClose, children }: Pick<RecipeEditorProps, "recipe" | "inline" | "run" | "onClose"> & { children: ReactNode }) {
  const t = useT();
  const titleId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { if (inline) heading.current?.focus(); }, [inline]);
  if (run) return children;
  const title = t(recipe ? "Modifier le parcours" : "Créer un parcours");
  if (inline) return <section className="recipe-compose-inline" aria-labelledby={titleId}>
    <div className="section-heading"><h2 id={titleId} ref={heading} tabIndex={-1}>{title}</h2></div>
    {children}
  </section>;
  return <Dialog wide className="console-dialog--recipe" title={title} onClose={onClose}>{children}</Dialog>;
}
