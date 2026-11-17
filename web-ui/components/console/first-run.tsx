"use client";

import { useState } from "react";
import { api } from "../../lib/client-api";
import { useT } from "../../lib/i18n";
import { isDeviceReady } from "../../lib/device-readiness";
import type { Data, Recipe, Workflow } from "../../lib/console-types";
import { ErrorNotice } from "./shared";
import { RecipeEditor } from "./recipe-editor";
import { Icon } from "./icons";

export function FirstRun({ data, canBuild, canManage, canLaunch, onLaunch, onOpen, onChanged }: {
  data: Data; canBuild: boolean; canManage: boolean; canLaunch: boolean;
  onLaunch: (workflow?: Workflow, ids?: string[]) => void; onOpen: (id: string) => void; onChanged: () => void;
}) {
  const t = useT();
  const [editing, setEditing] = useState(false), [draft, setDraft] = useState<Recipe | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const ready = data.devices.filter(isDeviceReady);
  const latest = data.runs.find(run => !run.workflow_id.startsWith("emulator-system-"));
  async function testDraft() {
    if (!draft || busy) return;
    setBusy(true); setError("");
    try {
      const published = await api<Recipe>(`console/recipes/${draft.id}/publish`, { revision: draft.revision });
      setDraft(published);
      const workflow = await api<Workflow>(`workflows/${encodeURIComponent(published.workflow_id)}/versions/${published.latest_version}`);
      onChanged(); onLaunch(workflow, ready.slice(0, 1).map(device => device.device_id));
    } catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="surface first-run" aria-labelledby="first-run-heading">
    <div className="surface-heading"><div><h2 id="first-run-heading">{t("Votre premier parcours réussi")}</h2><p>{t("Un appareil prêt, un objectif et un résultat visible.")}</p></div><Icon name="play" /></div>
    {error && <ErrorNotice message={error} />}
    <ol className="first-run-grid">
      <li><span className="recipe-step-number">1</span><h3>{t("Préparer un appareil")}</h3><p>{ready.length ? t("{count} appareil(s) prêt(s) dans la sélection chargée.", {count: ready.length}) : t("Allumez l’émulateur, préparez ses applications et vérifiez sa connexion.")}</p><a className="button button--secondary" href="/telephones">{t(canManage ? "Préparer un appareil" : "Appareils")}</a></li>
      <li><span className="recipe-step-number">2</span><h3>{t("Décrire mon objectif")}</h3><p>{draft ? draft.name : t("Écrivez ce que doit faire l’appareil. Les étapes sont préparées pour vous.")}</p>{canBuild && <button type="button" className="button button--secondary" onClick={() => setEditing(true)}>{t(draft ? "Créer un autre parcours" : "Créer un parcours")}</button>}{draft && canLaunch ? <button type="button" className="button button--primary" disabled={busy || !ready.length} onClick={() => void testDraft()}>{t("Publier et tester")}</button> : canLaunch && data.workflows.length > 0 && <button type="button" className="text-button" disabled={!ready.length} onClick={() => onLaunch(undefined, ready.slice(0, 1).map(device => device.device_id))}>{t("Tester un parcours publié")}</button>}</li>
      <li><span className="recipe-step-number">3</span><h3>{t("Vérifier le résultat")}</h3><p>{t("Suivez l’écran en direct, puis consultez les captures et le résultat de chaque étape.")}</p>{latest ? <button type="button" className="button button--secondary" onClick={() => onOpen(latest.id)}>{t("Voir la dernière exécution")}</button> : <span className="small-copy">{t("Le résultat apparaîtra après votre premier lancement.")}</span>}</li>
    </ol>
    {editing && <RecipeEditor onClose={() => setEditing(false)} onSaved={recipe => {setEditing(false); if (recipe) setDraft(recipe); onChanged();}} />}
  </section>;
}
