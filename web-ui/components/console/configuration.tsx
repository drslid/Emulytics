"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/client-api";
import type { JourneyModels, User } from "../../lib/console-types";
import { useT } from "../../lib/i18n";
import { Icon } from "./icons";
import { ChatgptConnectionPanel } from "./chatgpt-connection";

const settings = [
  { href: "/profil", title: "Mon profil", copy: "Vos informations personnelles et votre langue.", icon: "users", permission: null },
  { href: "/profil#securite", title: "Sécurité du compte", copy: "Votre mot de passe, votre application 2FA et vos codes de secours.", icon: "shield", permission: null },
  { href: "/telephones", title: "Appareils et applications", copy: "Les connexions des appareils, les émulateurs et leurs applications.", icon: "phone", permission: "devices.read" },
  { href: "/planifications", title: "Planifications", copy: "Les horaires, les fuseaux et la fréquence de vos parcours.", icon: "clock", permission: "schedules.read" },
  { href: "/utilisateurs", title: "Utilisateurs et rôles", copy: "Les comptes locaux, les profils et les droits d’accès.", icon: "users", permission: "users.manage" }
] as const;

export function Configuration({ user }: { user: User }) {
  const t = useT();
  const [models, setModels] = useState<JourneyModels | null>(null);
  const [providerError, setProviderError] = useState(false);
  const loadProviders = useCallback(async () => {
    setProviderError(false);
    try { setModels(await api<JourneyModels>("console/recipes/providers")); }
    catch { setProviderError(true); }
  }, []);
  useEffect(() => { void loadProviders(); }, [loadProviders]);
  return <div className="configuration-layout">
    <ChatgptConnectionPanel key={user.id} user={user} />
    <section className="surface chatgpt-connection" aria-labelledby="journey-providers-heading">
      <div className="chatgpt-heading"><div><h2 id="journey-providers-heading">{t("Autres fournisseurs IA")}</h2>
        <p>{t("Choisissez un fournisseur configuré lors de la préparation d’un parcours.")}</p></div></div>
      {models ? <dl className="journey-provider-list">
        {([ ["ollama", "Ollama"], ["deepseek", "DeepSeek"] ] as const).map(([id, label]) => <div key={id}>
          <dt>{label}</dt><dd>{models[id] ? <bdi>{models[id]}</bdi> : t("Non configuré")}</dd>
        </div>)}
      </dl> : <div className="chatgpt-loading" aria-busy={!providerError}>
        <p role="status">{t(providerError ? "Impossible de charger les fournisseurs IA." : "Chargement…")}</p>
        {providerError && <button type="button" className="button button--secondary" onClick={() => void loadProviders()}>{t("Réessayer")}</button>}
      </div>}
    </section>
    <section aria-labelledby="configuration-settings-heading"><div className="section-heading"><div><h2 id="configuration-settings-heading">{t("Vos autres réglages")}</h2><p>{t("Retrouvez chaque réglage dans sa section.")}</p></div></div><div className="configuration-settings-grid tw:grid tw:grid-cols-1 tw:gap-4 tw:min-[720px]:grid-cols-2">{settings.filter(setting => !setting.permission || user.permissions.includes(setting.permission)).map(setting => <a className="surface configuration-setting" href={setting.href} key={setting.href}><span className="configuration-setting-icon"><Icon name={setting.icon} size={21} /></span><div><h3>{t(setting.title)}</h3><p>{t(setting.copy)}</p></div><Icon name="arrow" size={18} /></a>)}</div></section>
  </div>;
}
