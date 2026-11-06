"use client";

import { useT } from "../../lib/i18n";

import type { User } from "../../lib/console-types";
import { Icon } from "./icons";

export function Security({ user, onLogout }: { user: User; onLogout: () => void }) {
  const t = useT();
  return <div className="security-layout"><section className="surface security-card"><span className="secure-symbol secure-symbol--large"><Icon name="shield" size={32} /></span><h2>{t("Votre accès est protégé")}</h2><p>{t("Connecté en tant que")} <strong>{user.username}</strong>.</p><div className="security-line"><span><Icon name="key" />{t("Mot de passe")}</span><strong>{t("Requis à la connexion")}</strong></div><div className="security-line"><span><Icon name="shield" />{t("Validation en deux étapes")}</span><span className="status-badge status-badge--green"><Icon name="check" size={14} />{t("Activée")}</span></div><div className="security-line"><span><Icon name="clock" />{t("Session")}</span><strong>{t("Expire au plus tard après 8 h")}</strong></div><div className="security-actions"><button className="button button--secondary" onClick={onLogout}><Icon name="logout" size={18} />{t("Se déconnecter")}</button></div></section><aside className="surface security-card"><h2>{t("Gardez vos codes de secours")}</h2><p>{t("Ils permettent de retrouver l’accès si votre application d’authentification n’est plus disponible. Chaque code ne peut servir qu’une fois.")}</p><p>{t("Vos codes ont été affichés lors de l’activation. Conservez-les hors de cette console, dans un endroit sûr.")}</p><hr /><h3>{t("Besoin de réinitialiser votre accès ?")}</h3><p>{t("Un administrateur peut réinitialiser votre mot de passe ou la validation en deux étapes depuis la gestion des utilisateurs.")}</p></aside></div>;
}
