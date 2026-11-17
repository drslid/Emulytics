"use client";

import { useState } from "react";
import { api, ApiError } from "../../lib/client-api";
import type { JourneyProviderId } from "../../lib/console-types";
import { useT } from "../../lib/i18n";
import { ErrorNotice } from "./shared";

const errors = {
  chatgpt_required: "Connectez votre compte ChatGPT avant de tester.",
  provider_auth_failed: "Le fournisseur a refusé les identifiants.",
  provider_model_unavailable: "Le modèle configuré est introuvable.",
  provider_unconfigured: "Vérifiez l’adresse, le modèle et les identifiants du fournisseur."
};

export function ProviderConnectionTest({ provider, disabled, unsaved }: {
  provider: JourneyProviderId; disabled?: boolean; unsaved?: boolean;
}) {
  const t = useT();
  const [checking, setChecking] = useState(false);
  const [tested, setTested] = useState(false);
  const [error, setError] = useState("");

  async function check() {
    setChecking(true);
    setTested(false);
    setError("");
    try {
      const result = await api<{ provider: JourneyProviderId; status: "ok" }>("console/account/ai-providers/test", { provider });
      if (result?.provider !== provider || result.status !== "ok") throw new Error();
      setTested(true);
    } catch (failure) {
      const code = failure instanceof ApiError ? failure.code : undefined;
      if (code && Object.hasOwn(errors, code)) setError(t(errors[code as keyof typeof errors]));
      else if (failure instanceof ApiError && [403, 429].includes(failure.status)) setError(failure.message);
      else setError(t("Le test a échoué. Vérifiez la connexion et réessayez."));
    } finally {
      setChecking(false);
    }
  }

  return <div className="provider-connection-test" aria-busy={checking}>
    <button type="button" className="button button--secondary" disabled={disabled || unsaved || checking} onClick={() => void check()}>
      {t(checking ? "Test de connexion…" : "Tester la connexion")}
    </button>
    {unsaved ? <p className="small-copy">{t("Enregistrez les modifications avant de tester.")}</p>
      : error ? <ErrorNotice message={error} />
      : tested && <p className="notice notice--success" role="status">{t("Connexion vérifiée.")}</p>}
  </div>;
}
