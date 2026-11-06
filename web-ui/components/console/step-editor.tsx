"use client";

import { useT } from "../../lib/i18n";
import type { Step } from "../../lib/console-types";
import { changeEditorAction, editorActions, editorArgumentField, editorRecord, editorStepTargets, patchEditorArgument, patchEditorTarget } from "../../lib/workflow-editor";

const labels: Record<string, string> = {
  resource_id: "Identifiant de l’élément", text: "Texte exact", text_contains: "Texte contenant",
  content_desc: "Description accessible", class: "Classe Android", checked: "Élément coché", focused: "Élément actif",
};

function selectorSummary(selector: Record<string, unknown>) {
  return Object.entries(selector).map(([key, value]) => `${key}: ${String(value)}`).join(" · ");
}

export function stepPreview(step: Step): string {
  const field = editorArgumentField(step.action);
  if (field) return String(step.args?.[field.key] ?? "");
  if (step.action === "tap") return editorStepTargets(step).map(selectorSummary).join(" / ") || `${step.args?.x ?? "—"}, ${step.args?.y ?? "—"}`;
  return step.id.replace(/-/g, " ");
}

function SelectorEditor({ selector, onChange }: { selector: Record<string, unknown>; onChange: (selector: Record<string, unknown>) => void }) {
  const t = useT();
  const keys = Object.keys(labels).filter(key => Object.hasOwn(selector, key));
  const missing = Object.keys(labels).filter(key => !Object.hasOwn(selector, key));
  return <div className="selector-editor">
    {keys.map(key => <div className="selector-criterion" key={key}>
      <label>{t(labels[key])}
        {key === "checked" || key === "focused" ? <select value={String(selector[key])} onChange={event => onChange({ ...selector, [key]: event.target.value === "true" })}>
          <option value="true">{t("Oui")}</option><option value="false">{t("Non")}</option>
        </select> : <input dir="ltr" required value={String(selector[key] ?? "")} onChange={event => onChange({ ...selector, [key]: event.target.value })} />}
      </label>
      <button type="button" className="text-button" aria-label={t("Retirer le critère {name}", { name: t(labels[key]) })} onClick={() => {
        const next = { ...selector }; delete next[key]; onChange(next);
      }}>×</button>
    </div>)}
    {missing.length > 0 && <label className="selector-add">{t("Ajouter un critère")}
      <select value="" onChange={event => { if (event.target.value) onChange({ ...selector, [event.target.value]: ["checked", "focused"].includes(event.target.value) ? true : "" }); }}>
        <option value="">{t("Choisir un critère…")}</option>
        {missing.map(key => <option key={key} value={key}>{t(labels[key])}</option>)}
      </select>
    </label>}
  </div>;
}

function AssertionEditor({ assertion, onChange, depth = 0 }: { assertion: Record<string, unknown>; onChange: (assertion: Record<string, unknown>) => void; depth?: number }) {
  const t = useT();
  return <div className="assertion-check">
    <label>{t("Type de vérification")}<select value={String(assertion.type ?? "")} onChange={event => {
      const type = event.target.value;
      onChange(type === "ui" ? { type, selector: { text: "" } } : type === "url" ? { type, host: "fr.wikipedia.org" } : { type, value: "com.android.chrome" });
    }}>
      <option value="package">{t("Application au premier plan")}</option>
      <option value="package_installed">{t("Application installée")}</option>
      <option value="ui">{t("Élément visible")}</option>
      <option value="url">{t("Domaine de la page")}</option>
      {assertion.type === "all" && <option value="all">{t("Plusieurs vérifications (modèle)")}</option>}
      {!["package", "package_installed", "ui", "url", "all"].includes(String(assertion.type)) && <option value={String(assertion.type ?? "")}>{String(assertion.type ?? "")}</option>}
    </select></label>
    <AssertionFields assertion={assertion} onChange={onChange} depth={depth} />
  </div>;
}

function AssertionFields({ assertion, onChange, depth }: { assertion: Record<string, unknown>; onChange: (assertion: Record<string, unknown>) => void; depth: number }) {
  const t = useT();
  const kind = assertion.type;
  if (kind === "all" && Array.isArray(assertion.checks) && assertion.checks.every(editorRecord) && depth < 5) {
    const checks = assertion.checks as Record<string, unknown>[];
    return <div className="assertion-checks">{checks.map((check, index) => <div className="assertion-check" key={index}>
      <strong>{t("Vérification {n}", { n: index + 1 })}</strong>
      <AssertionEditor assertion={check} depth={depth + 1} onChange={next => onChange({ ...assertion, checks: checks.map((item, i) => i === index ? next : item) })} />
    </div>)}</div>;
  }
  if (kind === "ui" && editorRecord(assertion.selector)) return <SelectorEditor selector={assertion.selector} onChange={selector => onChange({ ...assertion, selector })} />;
  if (kind === "package" || kind === "package_installed") return <label>
    {t(kind === "package" ? "Application au premier plan" : "Application installée")}
    <input dir="ltr" required value={String(assertion.value ?? (kind === "package_installed" ? "com.android.chrome" : ""))} onChange={event => onChange({ ...assertion, value: event.target.value })} />
  </label>;
  if (kind === "url") return <div className="form-grid">
    <label>{t("Domaine de la page")}<input dir="ltr" required value={String(assertion.host ?? "")} onChange={event => onChange({ ...assertion, host: event.target.value })} /></label>
    <label>{t("Chemin contenant")}<input dir="ltr" value={String(assertion.path_contains ?? "")} onChange={event => {
      const next = { ...assertion };
      if (event.target.value) next.path_contains = event.target.value; else delete next.path_contains;
      onChange(next);
    }} /></label>
  </div>;
  return <p className="editor-help">{t("Cette vérification se modifie dans JSON avancé.")}</p>;
}

export function StepEditor({ step, onChange }: { step: Step; onChange: (step: Step) => void }) {
  const t = useT();
  const field = editorArgumentField(step.action);
  const targets = editorStepTargets(step);
  const argumentSelector = step.action === "tap" && editorRecord(step.args?.selector);
  const coordinateTap = step.action === "tap" && !targets.length;
  const numericKeys = step.action === "swipe" ? ["x1", "y1", "x2", "y2", "duration_ms"] : coordinateTap ? ["x", "y"] : [];
  return <div className="step-editor-fields">
    <label>{t("Action")}
      <select value={step.action} onChange={event => onChange(changeEditorAction(step, event.target.value))}>
        {Object.entries(editorActions).map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}
      </select>
    </label>
    {field && <label>{t(field.label)}<input required dir="ltr" maxLength={field.key === "text" ? 16384 : 4096} value={String(step.args?.[field.key] ?? (step.action === "ensure_package" ? "com.android.chrome" : ""))} onChange={event => onChange(patchEditorArgument(step, field.key, event.target.value))} /></label>}
    {step.action === "type_text" && <label className="checkbox-label"><input type="checkbox" checked={step.args?.clear === true} onChange={event => onChange(patchEditorArgument(step, "clear", event.target.checked))} />{t("Effacer le texte avant la saisie")}</label>}
    {numericKeys.length > 0 && <div className="step-coordinate-grid">{numericKeys.map(key => <label key={key}>{key === "duration_ms" ? t("Durée (ms)") : key.toUpperCase()}
      <input type="number" min={key === "duration_ms" ? 1 : 0} max={key === "duration_ms" ? 10000 : 100000} required value={typeof step.args?.[key] === "number" ? step.args[key] as number : ""} onChange={event => onChange(patchEditorArgument(step, key, event.target.value === "" ? undefined : Number(event.target.value)))} />
    </label>)}</div>}
    {["tap", "type_text"].includes(step.action) && <details className="step-options">
      <summary>{t("Élément ciblé")}{targets.length > 0 && <span>{selectorSummary(targets[0])}</span>}</summary>
      <div className="step-options-content">
        {targets.map((selector, index) => <div className="target-alternative" key={index}>
          <div className="step-toolbar"><strong>{t("Cible {n}", { n: index + 1 })}</strong>
            <button type="button" className="text-button" onClick={() => {
              if (argumentSelector) { const args = { ...step.args }; delete args.selector; onChange({ ...step, args }); }
              else onChange({ ...step, selectors: targets.filter((_, i) => i !== index) });
            }}>{t("Supprimer")}</button>
          </div>
          <SelectorEditor selector={selector} onChange={next => onChange(patchEditorTarget(step, index, next))} />
        </div>)}
        {!targets.length && <p className="editor-help">{t("Sans cible, la saisie utilise le champ actif et le toucher utilise les coordonnées.")}</p>}
        {!argumentSelector && targets.length < 8 && <button type="button" className="text-button" onClick={() => onChange({ ...step, selectors: [...targets, { resource_id: "" }] })}>{t("Ajouter une cible alternative")}</button>}
      </div>
    </details>}
    <details className="step-options">
      <summary>{t("Vérification après l’action")}<span>{String(step.assert?.type ?? "")}</span></summary>
      <div className="step-options-content"><AssertionEditor assertion={step.assert ?? {}} onChange={assertion => onChange({ ...step, assert: assertion })} /></div>
    </details>
    <details className="step-options">
      <summary>{t("Options de l’étape")}</summary>
      <div className="step-options-content">
        <label>{t("Délai maximal (ms)")}<input type="number" min={100} max={300000} value={step.timeout_ms ?? 10000} onChange={event => onChange({ ...step, timeout_ms: Number(event.target.value) })} /></label>
        <p className="editor-help">{t("Les conditions, la récupération et les autres paramètres sont conservés. Modifiez-les dans JSON avancé.")}</p>
        <code className="step-identity" dir="ltr">{step.id}</code>
      </div>
    </details>
  </div>;
}
