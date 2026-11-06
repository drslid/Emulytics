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

const argumentFields: Record<string, { key: string; label: string }> = {
  open_app: { key: "package_name", label: "Identifiant de l’application" },
  ensure_package: { key: "package", label: "Identifiant de l’application" },
  open_url: { key: "url", label: "Adresse web" },
  type_text: { key: "text", label: "Texte à saisir" },
  press_key: { key: "keycode", label: "Touche Android" },
};

export function editorActionLabel(action: string): string {
  return Object.hasOwn(editorActions, action) ? editorActions[action as keyof typeof editorActions] : action;
}

export function editorArgumentField(action: string): { key: string; label: string } | undefined {
  return Object.hasOwn(argumentFields, action) ? argumentFields[action] : undefined;
}

export function editorRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function freshEditorStep(action = "open_app"): Step {
  const args = action === "open_app" ? { package_name: "com.android.chrome" }
    : action === "open_url" ? { url: "https://fr.wikipedia.org/" }
      : action === "press_key" ? { keycode: "KEYCODE_ENTER" }
        : action === "type_text" ? { text: "", clear: true }
          : action === "ensure_package" ? { package: "com.android.chrome" }
            : action === "swipe" ? { x1: 500, y1: 1000, x2: 500, y2: 300, duration_ms: 400 } : {};
  return {
    id: `step-${crypto.randomUUID().slice(0, 8)}`, action, args,
    selectors: action === "tap" ? [{ resource_id: "" }]
      : action === "type_text" ? [{ class: "android.widget.EditText", focused: true }] : [],
    assert: { type: action === "ensure_package" ? "package_installed" : "package", value: "com.android.chrome" },
    timeout_ms: 30000, non_idempotent: false, recovery_budget: 0,
  };
}

export function changeEditorAction(step: Step, action: string): Step {
  const fresh = freshEditorStep(action);
  return { ...step, action, args: fresh.args, selectors: fresh.selectors };
}

export function duplicateEditorStep(step: Step): Step {
  return { ...structuredClone(step), id: `step-${crypto.randomUUID().slice(0, 8)}` };
}

export function patchEditorArgument(step: Step, key: string, value: unknown): Step {
  return { ...step, args: { ...step.args, [key]: value } };
}

export function editorStepTargets(step: Step): Record<string, unknown>[] {
  return step.action === "tap" && editorRecord(step.args?.selector)
    ? [step.args.selector] : step.selectors ?? [];
}

export function patchEditorTarget(step: Step, index: number, selector: Record<string, unknown>): Step {
  if (step.action === "tap" && editorRecord(step.args?.selector))
    return patchEditorArgument(step, "selector", selector);
  return { ...step, selectors: (step.selectors ?? []).map((item, i) => i === index ? selector : item) };
}

/** Guard only the shape the visual editor reads; the API validates executable behavior. */
export function parseEditorSteps(source: string): Step[] {
  const value: unknown = JSON.parse(source);
  if (!Array.isArray(value) || value.length < 1 || value.length > 14)
    throw new Error("Invalid editor steps");
  const ids = new Set<string>();
  for (const step of value) {
    if (
      !editorRecord(step) ||
      typeof step.id !== "string" ||
      !step.id ||
      ids.has(step.id) ||
      typeof step.action !== "string" ||
      !Object.hasOwn(editorActions, step.action) ||
      (step.args !== undefined && !editorRecord(step.args)) ||
      (step.selectors !== undefined &&
        (!Array.isArray(step.selectors) || !step.selectors.every(editorRecord))) ||
      !editorRecord(step.assert) ||
      typeof step.assert.type !== "string"
    ) {
      throw new Error("Invalid editor step");
    }
    ids.add(step.id);
  }
  return value as Step[];
}
