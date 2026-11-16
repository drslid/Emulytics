"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../../lib/client-api";
import type { AIProviderSettings, JourneyProviderId } from "../../lib/console-types";
import { useT } from "../../lib/i18n";
import { ErrorNotice } from "./shared";

const settingsPath = "console/account/ai-providers";
const providerNames = { openai: "OpenAI", ollama: "Ollama", deepseek: "DeepSeek" };

type SettingsDraft = {
  active_provider: JourneyProviderId;
  ollama_url: string;
  ollama_model: string;
  deepseek_model: string;
  deepseek_key: string;
  clear_key: boolean;
};

function makeDraft(settings: AIProviderSettings): SettingsDraft {
  return {
    active_provider: settings.active_provider,
    ollama_url: settings.ollama.url ?? "",
    ollama_model: settings.ollama.model ?? "",
    deepseek_model: settings.deepseek.model,
    deepseek_key: "",
    clear_key: false
  };
}

function changedFields(settings: AIProviderSettings, draft: SettingsDraft) {
  const current = makeDraft(settings);
  const change: Partial<Omit<SettingsDraft, "clear_key" | "deepseek_key"> & { deepseek_key: string | null }> = {};
  if (draft.active_provider !== current.active_provider) change.active_provider = draft.active_provider;
  if (draft.ollama_url.trim() !== current.ollama_url) change.ollama_url = draft.ollama_url.trim();
  if (draft.ollama_model.trim() !== current.ollama_model) change.ollama_model = draft.ollama_model.trim();
  if (draft.deepseek_model.trim() !== current.deepseek_model) change.deepseek_model = draft.deepseek_model.trim();
  if (draft.clear_key) change.deepseek_key = null;
  else if (draft.deepseek_key.trim()) change.deepseek_key = draft.deepseek_key.trim();
  return change;
}

export function AIProviderSettingsPanel() {
  const t = useT();
  const [settings, setSettings] = useState<AIProviderSettings | null>(null);
  const [draft, setDraft] = useState<SettingsDraft | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const load = useCallback(async () => {
    setError("");
    try {
      const current = await api<AIProviderSettings>(settingsPath);
      setSettings(current);
      setDraft(makeDraft(current));
    } catch {
      setError("Impossible de charger les fournisseurs IA.");
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  function change<K extends keyof SettingsDraft>(field: K, value: SettingsDraft[K]) {
    setDraft(previous => previous ? { ...previous, [field]: value } : previous);
    setError("");
    setSaved(false);
  }

  const patch = settings?.can_edit && draft ? changedFields(settings, draft) : {};
  const dirty = Object.keys(patch).length > 0;

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!settings?.can_edit || !dirty || saving) return;
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      const response = await api<AIProviderSettings | null>(settingsPath, patch, "PATCH");
      const current = response ?? await api<AIProviderSettings>(settingsPath);
      setSettings(current);
      setDraft(makeDraft(current));
      setSaved(true);
    } catch (failure) {
      if (failure instanceof ApiError && failure.code === "provider_unconfigured" && draft) {
        setError(t("{provider} est indisponible. Vérifiez sa configuration puis réessayez.", { provider: providerNames[draft.active_provider] }));
      } else {
        setError(failure instanceof ApiError && failure.status === 422
          ? "Vérifiez l’adresse, le modèle et les identifiants du fournisseur."
          : "Impossible d’enregistrer les réglages IA. Réessayez.");
      }
    } finally {
      setSaving(false);
    }
  }

  return <section className="surface chatgpt-connection" aria-labelledby="journey-providers-heading">
    <div className="chatgpt-heading">
      <div>
        <h2 id="journey-providers-heading">{t("Fournisseurs IA")}</h2>
        <p>{t("Le fournisseur par défaut et les réglages Ollama et DeepSeek sont communs à toute l’installation.")}</p>
      </div>
    </div>
    {error && <ErrorNotice message={t(error)} />}
    {settings && draft ? <form onSubmit={save} aria-busy={saving}>
      <fieldset disabled={saving} className="ai-provider-settings">
        {settings.can_edit ? <label>{t("Fournisseur utilisé par défaut")}
          <select value={draft.active_provider} onChange={event => change("active_provider", event.target.value as JourneyProviderId)}>
            {Object.entries(providerNames).map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
        </label> : <dl className="ai-provider-default">
          <dt>{t("Fournisseur utilisé par défaut")}</dt>
          <dd>{providerNames[settings.active_provider]}</dd>
        </dl>}
        <div className="ai-provider-fields">
          <fieldset><legend>Ollama</legend>
            {settings.can_edit ? <>
              <label>{t("Adresse du serveur Ollama")}
                <input type="url" value={draft.ollama_url} maxLength={512} placeholder="http://host.docker.internal:11434" onChange={event => change("ollama_url", event.target.value)} />
              </label>
              <label>{t("Modèle Ollama")}
                <input value={draft.ollama_model} maxLength={128} onChange={event => change("ollama_model", event.target.value)} />
              </label>
            </> : settings.ollama.configured && <p><bdi>{settings.ollama.model}</bdi></p>}
            {!settings.ollama.configured && <p>{t("Non configuré")}</p>}
          </fieldset>
          <fieldset><legend>DeepSeek</legend>
            {settings.can_edit ? <>
              <label>{t("Clé API DeepSeek")}
                <input type="password" autoComplete="new-password" value={draft.deepseek_key} maxLength={512} disabled={draft.clear_key} onChange={event => change("deepseek_key", event.target.value)} />
                <span>{t(settings.deepseek.has_key ? "Clé API configurée" : "Non configuré")}</span>
              </label>
              <label>{t("Modèle DeepSeek")}
                <input value={draft.deepseek_model} maxLength={128} onChange={event => change("deepseek_model", event.target.value)} />
              </label>
              {settings.deepseek.has_saved_key && <label className="ai-provider-clear-key">
                <input type="checkbox" checked={draft.clear_key} onChange={event => {
                  change("clear_key", event.target.checked);
                  if (event.target.checked) change("deepseek_key", "");
                }} />{t("Retirer la clé DeepSeek")}
              </label>}
            </> : <p>{settings.deepseek.has_key ? <bdi>{settings.deepseek.model}</bdi> : t("Non configuré")}</p>}
          </fieldset>
        </div>
        {saved && <p className="notice notice--success" role="status">{t("Réglages IA enregistrés.")}</p>}
        {settings.can_edit && <button type="submit" className="button button--primary" disabled={!dirty}>{t("Enregistrer")}</button>}
      </fieldset>
    </form> : <div className="chatgpt-loading" aria-busy={!error}>
      {error ? <button type="button" className="button button--secondary" onClick={() => void load()}>{t("Réessayer")}</button>
        : <p role="status">{t("Chargement…")}</p>}
    </div>}
  </section>;
}
