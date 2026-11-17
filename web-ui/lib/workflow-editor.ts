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
  open_settings: "Ouvrir les paramètres du téléphone",
  read_device_info: "Lire la version Android",
};

const knownApplicationNames: Record<string, string> = {
  "com.android.settings": "Paramètres du téléphone",
  "com.android.chrome": "Chrome",
};

export function containsApplicationIdentifier(text: string) {
  return /\b[a-z][a-z\d_]*(?:\.[a-z\d_]+)+\b/i.test(text);
}

function applicationName(value: unknown, names: Record<string, string>) {
  if (typeof value !== "string") return undefined;
  const label = Object.hasOwn(names, value) ? names[value] : undefined;
  if (typeof label === "string" && label.trim() && !containsApplicationIdentifier(label)) return label.trim();
  return Object.hasOwn(knownApplicationNames, value) ? knownApplicationNames[value] : undefined;
}

type CheckSummary = { label: string; app?: string };

function checkSummaries(check: unknown, names: Record<string, string>, depth = 0): CheckSummary[] {
  if (!check || typeof check !== "object" || !("type" in check) || depth > 5) return [];
  if (check.type === "all" && "checks" in check && Array.isArray(check.checks)) {
    return check.checks.flatMap(item => checkSummaries(item, names, depth + 1));
  }
  if (check.type === "package" || check.type === "package_installed") {
    return [{ label: check.type === "package" ? "Application au premier plan" : "Application installée",
      app: "value" in check ? applicationName(check.value, names) : undefined }];
  }
  if (check.type === "url") return [{ label: "Domaine de la page" }];
  if (check.type === "ui") return [{ label: "Élément visible" }];
  return [];
}

export function workflowStepPreview(step: Step, applicationNames: Record<string, string> = {}) {
  return {
    label: Object.hasOwn(editorActions, step.action)
      ? editorActions[step.action as keyof typeof editorActions] : "Action Android",
    app: step.action === "open_app" || step.action === "ensure_package"
      ? applicationName(step.args?.[step.action === "open_app" ? "package_name" : "package"], applicationNames)
      : undefined,
    section: step.action === "open_settings" && step.args?.section === "about" ? "À propos du téléphone" : undefined,
    checks: checkSummaries(step.assert, applicationNames),
  };
}
