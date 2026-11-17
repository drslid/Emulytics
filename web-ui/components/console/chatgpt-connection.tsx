"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../lib/client-api";
import { CHATGPT_HELP_URL, chatgptNeedsPolling, expireChatgptLogin, parseChatgptConnection, type ChatgptConnection } from "../../lib/chatgpt";
import { useLocale, useT } from "../../lib/i18n";
import { ErrorNotice } from "./shared";
import { Icon } from "./icons";
import { ProviderConnectionTest } from "./provider-connection-test";

const labels = { disconnected: "Non connecté", starting: "Préparation de la connexion…", pending: "En attente de votre confirmation", connected: "Connecté", expired: "Code expiré", error: "Connexion à réessayer" };
const errors: Record<string, string> = {
  login_failed: "La connexion ChatGPT n’a pas abouti. Réessayez ou consultez l’aide.",
  login_expired: "Ce code a expiré. Demandez un nouveau code pour continuer.",
  login_interrupted: "La connexion ChatGPT n’a pas abouti. Réessayez ou consultez l’aide.",
  protocol_error: "La connexion ChatGPT est momentanément indisponible. Réessayez.",
  provider_unavailable: "La connexion ChatGPT est momentanément indisponible. Réessayez.",
  login_cancelled: "Connexion annulée.",
  denied: "La connexion a été refusée dans ChatGPT. Vous pouvez réessayer.",
  access_denied: "La connexion a été refusée dans ChatGPT. Vous pouvez réessayer.",
  expired: "Ce code a expiré. Demandez un nouveau code pour continuer.",
  device_auth_disabled: "Activez la connexion par code d’appareil dans les paramètres de sécurité de ChatGPT, puis réessayez.",
  unavailable: "La connexion ChatGPT est momentanément indisponible. Réessayez."
};
const invalidResponse = "L’état de la connexion ChatGPT est indisponible. Réessayez.";

export function ChatgptConnectionPanel() {
  const t = useT(), { locale } = useLocale();
  const [connection, setConnection] = useState<ChatgptConnection | null>(null), [error, setError] = useState("");
  const [busy, setBusy] = useState<"login" | "cancel" | "disconnect" | null>(null), [refreshing, setRefreshing] = useState(false), [notice, setNotice] = useState("");
  const sequence = useRef(0), mounted = useRef(false), loading = useRef(false), mutating = useRef(false);
  const current = useRef<ChatgptConnection | null>(null), nextPoll = useRef(0), intent = useRef<string | null>(null);
  const update = useCallback((value: ChatgptConnection) => {
    const previous = current.current;
    const result = expireChatgptLogin(value, Date.now());
    current.current = result; setConnection(result);
    if (previous?.status !== result.status) setNotice("");
    nextPoll.current = Date.now() + result.poll_interval_seconds * 1000;
    if (["connected", "expired", "error"].includes(result.status) || result.status === "disconnected" && chatgptNeedsPolling(previous)) intent.current = null;
  }, []);
  const load = useCallback(async () => {
    if (!mounted.current || loading.current || mutating.current || document.visibilityState === "hidden") return;
    const request = ++sequence.current; loading.current = true; setRefreshing(true);
    try {
      const result = parseChatgptConnection(await api<unknown>("console/account/chatgpt"));
      if (!mounted.current || request !== sequence.current) return;
      update(result); setError("");
    } catch (failure) {
      if (!mounted.current || request !== sequence.current) return;
      if (failure instanceof ApiError && [401, 403].includes(failure.status)) { current.current = null; setConnection(null); intent.current = null; }
      setError(failure instanceof ApiError ? failure.message : invalidResponse);
      nextPoll.current = Date.now() + 5000;
    } finally { if (request === sequence.current) { loading.current = false; if (mounted.current) setRefreshing(false); } }
  }, [update]);

  useEffect(() => {
    mounted.current = true; void load();
    function tick() {
      const previous = current.current;
      if (previous) {
        const expired = expireChatgptLogin(previous, Date.now());
        if (expired !== previous) { update(expired); setNotice(""); }
      }
      if (chatgptNeedsPolling(current.current) && Date.now() >= nextPoll.current) void load();
    }
    function visibility() {
      tick();
      if (document.visibilityState === "hidden") { sequence.current++; loading.current = false; setRefreshing(false); }
      else void load();
    }
    const timer = setInterval(tick, 1000); document.addEventListener("visibilitychange", visibility);
    return () => { mounted.current = false; sequence.current++; current.current = null; intent.current = null; clearInterval(timer); document.removeEventListener("visibilitychange", visibility); };
  }, [load, update]);

  async function act(action: "login" | "cancel" | "disconnect") {
    if (mutating.current) return;
    mutating.current = true; sequence.current++; loading.current = false; setRefreshing(false); setBusy(action); setError(""); setNotice("");
    if (action === "login") intent.current ??= crypto.randomUUID();
    const request = sequence.current;
    try {
      const result = parseChatgptConnection(await (action === "login" ? api<unknown>("console/account/chatgpt/login", { idempotency_key: intent.current })
        : action === "cancel" ? api<unknown>("console/account/chatgpt/cancel", {}) : api<unknown>("console/account/chatgpt", {}, "DELETE")));
      if (!mounted.current || request !== sequence.current) return;
      update(result);
      if (action !== "login") intent.current = null;
      if (action === "disconnect") {
        if (result.status === "disconnected") setNotice("Votre compte ChatGPT a été déconnecté d’Emulytix.");
        else setError(invalidResponse);
      }
    } catch (failure) {
      if (!mounted.current || request !== sequence.current) return;
      if (failure instanceof ApiError && [401, 403].includes(failure.status)) { current.current = null; setConnection(null); }
      if (failure instanceof ApiError && [401, 403, 404, 409, 422].includes(failure.status)) intent.current = null;
      setError(failure instanceof ApiError ? failure.message : invalidResponse);
    } finally {
      mutating.current = false;
      if (mounted.current) { setBusy(null); if (request !== sequence.current && document.visibilityState !== "hidden") void load(); }
    }
  }
  const login = connection?.login, pending = chatgptNeedsPolling(connection);
  const stamp = (value: string | null | undefined) => value ? new Intl.DateTimeFormat(locale, { dateStyle: "short", timeStyle: "medium", calendar: "gregory" }).format(new Date(value)) : "—";
  async function copy() {
    const value = current.current?.login;
    if (!value || Date.now() >= Date.parse(value.expires_at)) return;
    try { await navigator.clipboard.writeText(value.user_code); if (mounted.current && current.current?.login?.id === value.id) setNotice("Code copié."); }
    catch { if (mounted.current) setNotice("La copie automatique est indisponible. Sélectionnez le code pour le copier."); }
  }
  return <details className="ai-provider-option" name="ai-provider" data-provider="openai">
    <summary className="ai-provider-summary">
      <span className="ai-provider-name"><strong>OpenAI</strong><small>{t("Votre connexion personnelle")}</small></span>
      <span className="ai-provider-status" role="status">{t(error ? "État non confirmé" : connection ? labels[connection.status] : "Chargement…")}</span>
    </summary>
    <div className="chatgpt-connection">
    {error && <ErrorNotice message={t(error)} />}{notice && <p className="notice notice--info" role="status">{t(notice)}</p>}
    {!connection ? <div className="chatgpt-loading" aria-busy={refreshing}><p>{t(refreshing ? "Vérification de votre connexion ChatGPT…" : invalidResponse)}</p>{error && <button type="button" className="button button--secondary" disabled={refreshing || !!busy} onClick={() => void load()}>{t("Réessayer")}</button>}</div> : <>
      {!connection.available && <p className="notice notice--warning">{t("La connexion ChatGPT n’est pas disponible sur cette installation.")}</p>}
      {connection.error_code && connection.status !== "expired" && <p className="notice notice--warning">{t(errors[connection.error_code] ?? "La connexion ChatGPT n’a pas abouti. Réessayez ou consultez l’aide.")}</p>}
      {connection.status === "connected" ? <div className="chatgpt-connected"><div className="chatgpt-account-details"><Icon name="check" size={24} /><dl><div><dt>{t("Compte ChatGPT")}</dt><dd><bdi>{connection.account?.email || t("Compte personnel connecté")}</bdi></dd></div>{connection.account?.plan_type && <div><dt>{t("Abonnement")}</dt><dd><bdi>{connection.account.plan_type}</bdi></dd></div>}{connection.connected_at && <div><dt>{t("Connecté depuis")}</dt><dd>{stamp(connection.connected_at)}</dd></div>}</dl></div><div className="chatgpt-actions"><ProviderConnectionTest provider="openai" disabled={!!busy || !connection.available} /><button type="button" className="button button--secondary" disabled={!!busy} onClick={() => void act("disconnect")}>{t(busy === "disconnect" ? "Déconnexion en cours…" : "Déconnecter ChatGPT d’Emulytix")}</button></div></div>
        : pending ? <div className="chatgpt-authorization">{login ? <><ol className="chatgpt-steps"><li>{t("Ouvrez ChatGPT et connectez-vous à votre compte.")}</li><li>{t("Saisissez ce code et confirmez la connexion.")}</li></ol><div className="chatgpt-code-block"><code dir="ltr" aria-label={t("Code à saisir dans ChatGPT")}>{login.user_code}</code><button type="button" className="button button--secondary" disabled={!!busy} onClick={() => void copy()}>{t("Copier le code")}</button></div><p className="chatgpt-expiry">{t("Code valable jusqu’à {time}", { time: stamp(login.expires_at) })}</p><a href={login.verification_url} target="_blank" rel="noopener noreferrer" className="button button--primary">{t("Ouvrir ChatGPT")}<Icon name="arrow" size={17} /></a><p className="chatgpt-awaiting">{t("En attente de votre confirmation dans ChatGPT. Cette page se met à jour automatiquement.")}</p></> : <p role="status">{t("Préparation de la connexion…")}</p>}<button type="button" className="text-button" disabled={!!busy} onClick={() => void act("cancel")}>{t(busy === "cancel" ? "Annulation…" : "Annuler cette connexion")}</button></div>
          : <div className="chatgpt-start">{connection.status === "expired" && <p className="notice notice--warning">{t("Ce code a expiré. Demandez un nouveau code pour continuer.")}</p>}<button type="button" className="button button--primary" disabled={!connection.available || !!busy} onClick={() => void act("login")}><Icon name="key" size={17} />{t(busy === "login" ? "Préparation de la connexion…" : connection.status === "expired" ? "Obtenir un nouveau code" : intent.current ? "Réessayer la connexion" : "Connecter mon compte ChatGPT")}</button></div>}
      {error && connection && <button type="button" className="text-button" disabled={refreshing || !!busy} onClick={() => void load()}><Icon name="refresh" size={16} />{t("Actualiser l’état")}</button>}
    </>}
    <div className="chatgpt-help"><p>{t("Si ChatGPT le demande, activez la connexion par code d’appareil dans ses paramètres de sécurité ou auprès de l’administrateur de votre espace ChatGPT.")}</p><a href={CHATGPT_HELP_URL} target="_blank" rel="noopener noreferrer">{t("Aide officielle : connexion par code d’appareil")}<Icon name="arrow" size={14} /></a></div>
    </div>
  </details>;
}
