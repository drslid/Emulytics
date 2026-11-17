"use client";

import type { User } from "../../lib/console-types";
import { useT } from "../../lib/i18n";
import { Icon } from "./icons";
import { ReleaseUpdatePanel, type ReleaseUpdates } from "./release-updates";
import { AIProviderSettingsPanel } from "./ai-provider-settings";

const settings = [
  { href: "/profil", title: "Mon profil", copy: "Vos informations personnelles et votre langue.", icon: "users", permission: null },
  { href: "/profil#securite", title: "Sécurité du compte", copy: "Votre mot de passe, votre application 2FA et vos codes de secours.", icon: "shield", permission: null },
  { href: "/telephones", title: "Appareils et applications", copy: "Les connexions des appareils, les émulateurs et leurs applications.", icon: "phone", permission: "devices.read" },
  { href: "/planifications", title: "Planifications", copy: "Les horaires, les fuseaux et la fréquence de vos parcours.", icon: "clock", permission: "schedules.read" },
  { href: "/utilisateurs", title: "Utilisateurs et rôles", copy: "Les comptes locaux, les profils et les droits d’accès.", icon: "users", permission: "users.manage" }
] as const;

export function Configuration({ user, releaseUpdates }: { user: User; releaseUpdates: ReleaseUpdates | null }) {
  const t = useT();
  return <div className="configuration-layout">
    <AIProviderSettingsPanel key={user.id} />
    {releaseUpdates && <ReleaseUpdatePanel updates={releaseUpdates} />}
    <section aria-labelledby="configuration-settings-heading"><div className="section-heading"><div><h2 id="configuration-settings-heading">{t("Vos autres réglages")}</h2><p>{t("Retrouvez chaque réglage dans sa section.")}</p></div></div><div className="configuration-settings-grid tw:grid tw:grid-cols-1 tw:gap-4 tw:min-[720px]:grid-cols-2">{settings.filter(setting => !setting.permission || user.permissions.includes(setting.permission)).map(setting => <a className="surface configuration-setting" href={setting.href} key={setting.href}><span className="configuration-setting-icon"><Icon name={setting.icon} size={21} /></span><div><h3>{t(setting.title)}</h3><p>{t(setting.copy)}</p></div><Icon name="arrow" size={18} /></a>)}</div></section>
  </div>;
}
