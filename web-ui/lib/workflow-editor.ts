import type { Step } from "./console-types";

export const editorActions = {
  open_app: "Ouvrir une application",
  open_url: "Ouvrir une page web",
  tap: "Toucher un élément",
  type_text: "Saisir un texte",
  press_key: "Appuyer sur une touche",
  screenshot: "Prendre une capture",
  ensure_package: "Vérifier une application",
  swipe: "Faire défiler",
};

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** Guard only the shape the visual editor reads; the API validates executable behavior. */
export function parseEditorSteps(source: string): Step[] {
  const value: unknown = JSON.parse(source);
  if (!Array.isArray(value) || value.length < 1 || value.length > 14)
    throw new Error("Invalid editor steps");
  const ids = new Set<string>();
  for (const step of value) {
    if (
      !record(step) ||
      typeof step.id !== "string" ||
      !step.id ||
      ids.has(step.id) ||
      typeof step.action !== "string" ||
      !Object.hasOwn(editorActions, step.action) ||
      (step.args !== undefined && !record(step.args)) ||
      (step.selectors !== undefined &&
        (!Array.isArray(step.selectors) || !step.selectors.every(record))) ||
      !record(step.assert) ||
      typeof step.assert.type !== "string"
    ) {
      throw new Error("Invalid editor step");
    }
    ids.add(step.id);
  }
  return value as Step[];
}
