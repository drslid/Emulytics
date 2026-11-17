"use client";

import { useRef } from "react";
import type { RunRecipeState } from "../../lib/run-authoring";
import { CardRecipeEditor } from "./card-recipe-editor";
import type { RecipeEditorProps } from "./recipe-editor-shared";
import { TechnicalRecipeEditor } from "./technical-recipe-editor";

export function RecipeEditor(props: RecipeEditorProps) {
  const runState = useRef<RunRecipeState>({}).current;
  const source = props.recipe ?? props.run?.source;
  return source && !source.cards?.length
    ? <TechnicalRecipeEditor {...props} runState={runState} />
    : <CardRecipeEditor {...props} runState={runState} />;
}
