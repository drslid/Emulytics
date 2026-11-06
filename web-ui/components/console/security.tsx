"use client";

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { ApiError, api } from "../../lib/client-api";
import type { User } from "../../lib/console-types";
import { useLocale, useT } from "../../lib/i18n";
import { Icon } from "./icons";
import { Dialog, ErrorNotice } from "./shared";

type SecurityState = {
  two_factor_enabled: boolean;
  recovery_codes_remaining: number;
  pending_enrollment_expires_at: string | null;
};
type Enrollment = { secret: string; otpauth_uri: string; expires_at: string };
type Action = "password" | "two-factor" | "recovery";
type Stage = "reauth" | "enroll" | "codes";

export function Security({
  user,
  onLogout,
}: {
  user: User;
  onLogout: () => void;
}) {
  const t = useT();
  const [state, setState] = useState<SecurityState | null>(null);
  const [modal, setModal] = useState<Action | null>(null);
  const [resume, setResume] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const load = useCallback(async () => {
    try {
      setState(await api<SecurityState>("console/account/security"));
      setError("");
    } catch (failure) {
      setError((failure as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  function open(action: Action, resumePending = false) {
    setNotice("");
    setResume(resumePending);
    setModal(action);
  }
  function changed(action: Action) {
    setNotice(
      t(
        action === "password"
          ? "Votre mot de passe a été modifié."
          : action === "two-factor"
            ? "Votre nouvelle application d’authentification est active."
            : "Vos codes de secours ont été renouvelés.",
      ),
    );
    void load();
  }
  return (
    <div className="section-stack">
      {error && (
        <div>
          <ErrorNotice message={error} />
          <button className="text-button" onClick={() => void load()}>
            {t("Réessayer")}
          </button>
        </div>
      )}
      {notice && (
        <div className="notice notice--success" role="status">
          <Icon name="check" />
          <span>{notice}</span>
        </div>
      )}
      <div className="security-layout">
        <section className="surface security-card">
          <span className="secure-symbol secure-symbol--large">
            <Icon name="shield" size={32} />
          </span>
          <h3>{t("Votre accès est protégé")}</h3>
          <p>
            {t("Connecté en tant que")} <strong>{user.username}</strong>.
          </p>
          <div className="security-line">
            <span>
              <Icon name="key" />
              {t("Mot de passe")}
            </span>
            <button
              className="text-button"
              onClick={() => open("password")}
              disabled={!state}
            >
              {t("Changer le mot de passe")}
            </button>
          </div>
          <div className="security-line">
            <span>
              <Icon name="shield" />
              {t("Validation en deux étapes")}
            </span>
            <span
              className={`status-badge status-badge--${state?.two_factor_enabled ? "green" : "neutral"}`}
            >
              <Icon name="check" size={14} />
              {state
                ? t(state.two_factor_enabled ? "Activée" : "À activer")
                : "…"}
            </span>
          </div>
          <p>
            {t(
              "Le 2FA reste obligatoire. Vous pouvez changer d’application sans perdre votre accès.",
            )}
          </p>
          <div className="button-row">
            <button
              className="button button--secondary"
              onClick={() => open("two-factor")}
              disabled={!state}
            >
              {t("Changer l’application 2FA")}
            </button>
            {state?.pending_enrollment_expires_at && (
              <button
                className="text-button"
                onClick={() => open("two-factor", true)}
              >
                {t("Reprendre")}
              </button>
            )}
          </div>
          <div className="security-line">
            <span>
              <Icon name="clock" />
              {t("Session")}
            </span>
            <strong>{t("Expire au plus tard après 8 h")}</strong>
          </div>
          <div className="security-actions">
            <button className="button button--secondary" onClick={onLogout}>
              <Icon name="logout" size={18} />
              {t("Se déconnecter")}
            </button>
          </div>
        </section>
        <aside className="surface security-card">
          <h3>{t("Gardez vos codes de secours")}</h3>
          <p>
            {t(
              "Ils permettent de retrouver l’accès si votre application d’authentification n’est plus disponible. Chaque code ne peut servir qu’une fois.",
            )}
          </p>
          <div className="security-line">
            <span>{t("Codes disponibles")}</span>
            <strong>{state?.recovery_codes_remaining ?? "…"}</strong>
          </div>
          <p>{t("Renouveler les codes rend les anciens inutilisables.")}</p>
          <button
            className="button button--secondary"
            disabled={!state}
            onClick={() => open("recovery")}
          >
            {t("Renouveler les codes de secours")}
          </button>
          <hr />
          <p>
            {t(
              "Changer le mot de passe, le 2FA ou les codes ferme vos autres sessions.",
            )}
          </p>
        </aside>
      </div>
      {modal && (
        <SecurityDialog
          action={modal}
          username={user.username}
          resume={resume}
          remainingCodes={state?.recovery_codes_remaining ?? 0}
          onClose={() => {
            setModal(null);
            void load();
          }}
          onChanged={changed}
        />
      )}
    </div>
  );
}

function PasswordField({
  label,
  name,
  value,
  onChange,
  autoComplete,
  autoFocus = false,
  minLength,
}: {
  label: string;
  name: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete: string;
  autoFocus?: boolean;
  minLength?: number;
}) {
  const t = useT();
  const [visible, setVisible] = useState(false);
  return (
    <label>
      {label}
      <div className="password-field">
        <input
          type={visible ? "text" : "password"}
          name={name}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          required
          maxLength={1024}
          minLength={minLength}
          autoComplete={autoComplete}
          autoFocus={autoFocus}
        />
        <button
          type="button"
          className="password-toggle"
          onClick={() => setVisible((current) => !current)}
          aria-label={t(
            visible ? "Masquer le mot de passe" : "Afficher le mot de passe",
          )}
          aria-pressed={visible}
        >
          {t(visible ? "Masquer" : "Afficher")}
        </button>
      </div>
    </label>
  );
}

function SecurityDialog({
  action,
  username,
  resume,
  remainingCodes,
  onClose,
  onChanged,
}: {
  action: Action;
  username: string;
  resume: boolean;
  remainingCodes: number;
  onClose: () => void;
  onChanged: (action: Action) => void;
}) {
  const { t, locale } = useLocale();
  const [stage, setStage] = useState<Stage>(
    resume && action === "two-factor" ? "enroll" : "reauth",
  );
  const [password, setPassword] = useState("");
  const [nextPassword, setNextPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState(false);
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null);
  const [codes, setCodes] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const submitting = useRef(false);
  const factorHelpId = useId();
  const allowRecovery =
    action === "two-factor"
      ? remainingCodes > 0
      : action === "password" && remainingCodes >= 2;
  const titles = {
    password: "Changer le mot de passe",
    "two-factor": "Changer l’application 2FA",
    recovery: "Renouveler les codes de secours",
  };
  function failureMessage(
    failure: unknown,
    context: "reauth" | "enrollment" | "confirm",
  ) {
    if (failure instanceof ApiError && failure.status === 403)
      return t(
        context === "reauth"
          ? allowRecovery
            ? "Mot de passe ou code incorrect. Utilisez un nouveau code ou un code de secours."
            : "Mot de passe ou code incorrect. Attendez un nouveau code dans votre application."
          : context === "enrollment"
            ? "La configuration a expiré. Recommencez le changement d’application."
            : "Code incorrect ou configuration expirée. Vérifiez le nouveau code, puis réessayez.",
      );
    return (failure as Error).message;
  }
  const loadEnrollment = useCallback(async () => {
    setError("");
    try {
      setEnrollment(
        await api<Enrollment>("console/account/two-factor/enrollment"),
      );
    } catch (failure) {
      setError(
        failure instanceof ApiError && failure.status === 403
          ? t(
              "La configuration a expiré. Recommencez le changement d’application.",
            )
          : (failure as Error).message,
      );
    }
  }, [t]);
  useEffect(() => {
    if (resume && action === "two-factor") void loadEnrollment();
  }, [resume, action, loadEnrollment]);
  function clearCredentials() {
    setPassword("");
    setCode("");
  }
  async function close(discard = false) {
    if (submitting.current) return;
    if (stage === "codes" && !saved && !discard) {
      setConfirmDiscard(true);
      return;
    }
    if (stage === "enroll") {
      submitting.current = true;
      setBusy(true);
      try {
        await api("console/account/two-factor/enrollment", {}, "DELETE");
      } catch {
        /* Pending enrollment expires without replacing the working factor. */
      } finally {
        submitting.current = false;
        setBusy(false);
      }
    }
    clearCredentials();
    setNextPassword("");
    setConfirmation("");
    setEnrollment(null);
    setCodes([]);
    onClose();
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || stage === "codes" || uncertain) return;
    if (action === "password" && stage === "reauth") {
      if ([...nextPassword].length < 12) {
        setError(t("Choisissez un mot de passe d’au moins 12 caractères."));
        return;
      }
      if (nextPassword !== confirmation) {
        setError(
          t(
            "Les deux mots de passe ne correspondent pas. Vérifiez la confirmation.",
          ),
        );
        return;
      }
      if (nextPassword === password) {
        setError(
          t("Choisissez un mot de passe différent du mot de passe actuel."),
        );
        return;
      }
    }
    submitting.current = true;
    setBusy(true);
    setError("");
    setUncertain(false);
    const context = stage === "enroll" ? "confirm" : "reauth";
    try {
      if (stage === "enroll") {
        const result = await api<{ recovery_codes: string[] }>(
          "console/account/two-factor/confirm",
          { code },
        );
        clearCredentials();
        setEnrollment(null);
        setCodes(result.recovery_codes);
        setStage("codes");
        onChanged(action);
      } else if (action === "password") {
        await api("console/account/password", {
          current_password: password,
          new_password: nextPassword,
          confirm_password: confirmation,
          code,
          recovery,
        });
        clearCredentials();
        setNextPassword("");
        setConfirmation("");
        onChanged(action);
        onClose();
      } else if (action === "two-factor") {
        await api("console/account/two-factor/start", {
          current_password: password,
          code,
          recovery,
        });
        clearCredentials();
        setRecovery(false);
        setStage("enroll");
        await loadEnrollment();
      } else {
        const result = await api<{ recovery_codes: string[] }>(
          "console/account/recovery-codes",
          { current_password: password, code, recovery },
        );
        clearCredentials();
        setCodes(result.recovery_codes);
        setStage("codes");
        onChanged(action);
      }
    } catch (failure) {
      setCode("");
      const unknown =
        failure instanceof ApiError && [0, 503].includes(failure.status);
      if (unknown && (action !== "two-factor" || stage === "enroll")) {
        setUncertain(true);
        setError(
          t(
            "La réponse a été interrompue. Reconnectez-vous avant de réessayer ; la modification a peut-être été enregistrée.",
          ),
        );
        clearCredentials();
        setNextPassword("");
        setConfirmation("");
      } else if (unknown && action === "two-factor" && stage === "reauth") {
        // A lost start response may already have created a pending secret; resume it by GET.
        try {
          const pending = await api<Enrollment>(
            "console/account/two-factor/enrollment",
          );
          clearCredentials();
          setRecovery(false);
          setEnrollment(pending);
          setStage("enroll");
        } catch {
          setError((failure as Error).message);
        }
      } else setError(failureMessage(failure, context));
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }
  async function reconnect() {
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    try {
      await api("auth/logout", {});
      window.location.assign("/connexion");
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }
  async function copyCodes() {
    try {
      await navigator.clipboard.writeText(codes.join("\n"));
      setCopied(true);
    } catch {
      setError(
        t(
          "La copie n’est pas disponible. Sélectionnez les informations pour les copier.",
        ),
      );
    }
  }
  function downloadCodes() {
    const blob = new Blob(
      [
        `${t("Emulytix — codes de secours")}\n${username}\n\n${codes.join("\n")}\n`,
      ],
      { type: "text/plain;charset=utf-8" },
    );
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `emulytix-${username}-recovery-codes.txt`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <Dialog
      title={t(titles[action])}
      description={
        stage === "reauth"
          ? t("Confirmez votre identité pour protéger votre compte.")
          : undefined
      }
      onClose={() => void close()}
    >
      <form className="dialog-form" onSubmit={submit}>
        {error && <ErrorNotice message={error} />}
        {uncertain ? (
          <>
            <p>
              {t(
                action === "password"
                  ? "À la reconnexion, utilisez le nouveau mot de passe si le changement a été enregistré."
                  : action === "two-factor"
                    ? "À la reconnexion, utilisez la nouvelle application si le changement a été enregistré."
                    : "Si les codes n’ont pas été reçus, renouvelez-les après reconnexion.",
              )}
            </p>
            <button
              type="button"
              className="button button--primary"
              disabled={busy}
              onClick={() => void reconnect()}
            >
              {t("← Revenir à la connexion")}
            </button>
          </>
        ) : stage === "codes" ? (
          <>
            <p>
              {t(
                "Conservez ces codes avant de continuer. Ils ne seront affichés qu’une fois.",
              )}
            </p>
            <div className="recovery-code-grid">
              {codes.map((item) => (
                <code key={item}>{item}</code>
              ))}
            </div>
            <div className="button-row">
              <button
                type="button"
                className="button button--secondary"
                onClick={downloadCodes}
              >
                {t("Télécharger les codes")}
              </button>
              <button
                type="button"
                className="text-button"
                onClick={() => void copyCodes()}
              >
                {t(copied ? "Copié" : "Copier les codes")}
              </button>
            </div>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={saved}
                onChange={(event) => {
                  setSaved(event.target.checked);
                  setConfirmDiscard(false);
                }}
              />
              <span>{t("J’ai conservé mes codes dans un endroit sûr.")}</span>
            </label>
            {confirmDiscard && (
              <div className="notice notice--warning" role="alert">
                <span>
                  {t(
                    "Ces codes ne seront plus affichés. Fermer sans les conserver ?",
                  )}
                </span>
              </div>
            )}
            <div className="dialog-footer">
              {confirmDiscard && (
                <button
                  type="button"
                  className="button button--secondary"
                  onClick={() => void close(true)}
                >
                  {t("Fermer sans conserver")}
                </button>
              )}
              <button
                type="button"
                className="button button--primary"
                disabled={!saved}
                onClick={() => void close()}
              >
                {t("J’ai conservé les accès")}
              </button>
            </div>
          </>
        ) : stage === "enroll" ? (
          <>
            <div className="notice notice--info">
              {t(
                "Votre application actuelle reste active jusqu’à la validation du nouveau code.",
              )}
            </div>
            {enrollment ? (
              <div className="enrollment-block">
                <p>
                  {t(
                    "Ajoutez Emulytix à votre application d’authentification.",
                  )}
                </p>
                <img
                  className="enrollment-qr"
                  src="/api/control/console/account/two-factor/enrollment/qr"
                  alt={t(
                    "QR code pour ajouter votre compte Emulytix à une application d’authentification",
                  )}
                  width={180}
                  height={180}
                />
                <details className="manual-secret">
                  <summary>{t("Je ne peux pas scanner le QR code")}</summary>
                  <p>
                    {t(
                      "Ajoutez un compte à code temporel (TOTP) et saisissez cette clé :",
                    )}
                  </p>
                  <code>{enrollment.secret}</code>
                </details>
                <p>
                  {t("Valable jusqu’à {time}", {
                    time: new Intl.DateTimeFormat(locale, {
                      timeStyle: "short",
                    }).format(new Date(enrollment.expires_at)),
                  })}
                </p>
              </div>
            ) : (
              <button
                type="button"
                className="button button--secondary"
                onClick={() => void loadEnrollment()}
              >
                {t("Recharger le QR code")}
              </button>
            )}
            <label>
              {t("Code de la nouvelle application")}
              <input
                name="new_factor_code"
                value={code}
                onChange={(event) =>
                  setCode(event.target.value.replace(/\D/g, "").slice(0, 6))
                }
                autoComplete="one-time-code"
                inputMode="numeric"
                pattern="[0-9]{6}"
                maxLength={32}
                required
              />
            </label>
            <div className="dialog-footer">
              <button
                type="button"
                className="button button--secondary"
                disabled={busy}
                onClick={() => void close()}
              >
                {t("Annuler")}
              </button>
              <button
                className="button button--primary"
                disabled={busy || !enrollment}
              >
                {t(busy ? "Vérification…" : "Activer la nouvelle application")}
              </button>
            </div>
            {!enrollment && (
              <button
                type="button"
                className="text-button"
                disabled={busy}
                onClick={() => {
                  setError("");
                  setStage("reauth");
                  clearCredentials();
                }}
              >
                {t("Recommencer")}
              </button>
            )}
          </>
        ) : (
          <>
            <PasswordField
              label={t("Mot de passe actuel")}
              name="current_password"
              value={password}
              onChange={setPassword}
              autoComplete="current-password"
              autoFocus
            />
            {action === "password" && (
              <>
                <PasswordField
                  label={t("Nouveau mot de passe")}
                  name="new_password"
                  value={nextPassword}
                  onChange={setNextPassword}
                  autoComplete="new-password"
                  minLength={12}
                />
                <PasswordField
                  label={t("Confirmer le nouveau mot de passe")}
                  name="confirm_password"
                  value={confirmation}
                  onChange={setConfirmation}
                  autoComplete="new-password"
                  minLength={12}
                />
                <p className="small-copy">
                  {t(
                    "Au moins 12 caractères, différents du mot de passe actuel.",
                  )}
                </p>
              </>
            )}
            <label>
              {t(recovery ? "Code de secours" : "Code à 6 chiffres")}
              <input
                name="current_factor_code"
                value={code}
                onChange={(event) =>
                  setCode(
                    recovery
                      ? event.target.value
                          .replace(/[\s-]/g, "")
                          .toUpperCase()
                          .slice(0, 16)
                      : event.target.value.replace(/\D/g, "").slice(0, 6),
                  )
                }
                autoComplete="one-time-code"
                inputMode={recovery ? "text" : "numeric"}
                pattern={recovery ? "[A-Fa-f0-9]{16}" : "[0-9]{6}"}
                maxLength={64}
                required
                aria-describedby={factorHelpId}
              />
              <span id={factorHelpId}>
                {t(
                  recovery
                    ? "Un code ne peut être utilisé qu’une seule fois."
                    : "Attendez un nouveau code si celui-ci a déjà servi à vous connecter.",
                )}
              </span>
            </label>
            {allowRecovery && (
              <button
                type="button"
                className="text-button"
                disabled={busy}
                onClick={() => {
                  setRecovery((current) => !current);
                  setCode("");
                }}
              >
                {t(
                  recovery
                    ? "Utiliser mon application d’authentification"
                    : "Utiliser un code de secours",
                )}
              </button>
            )}{" "}
            {recovery && action === "two-factor" && remainingCodes === 1 && (
              <div className="notice notice--warning">
                {t(
                  "Ce dernier code sera consommé dès la confirmation. Terminez le changement d’application avant de quitter.",
                )}
              </div>
            )}
            {action === "password" && remainingCodes < 2 && (
              <p className="small-copy">
                {t(
                  "Votre dernier code de secours doit rester disponible pour changer d’application.",
                )}
              </p>
            )}
            {action === "recovery" && (
              <p className="small-copy">
                {t(
                  "Utilisez votre application pour renouveler les codes. Si elle est perdue, changez d’application avec un code de secours.",
                )}
              </p>
            )}
            {action === "recovery" && (
              <div className="notice notice--warning">
                {t("Renouveler les codes rend les anciens inutilisables.")}
              </div>
            )}
            <div className="dialog-footer">
              <button
                type="button"
                className="button button--secondary"
                disabled={busy}
                onClick={() => void close()}
              >
                {t("Annuler")}
              </button>
              <button className="button button--primary" disabled={busy}>
                {t(
                  busy
                    ? "Vérification…"
                    : action === "password"
                      ? "Enregistrer"
                      : "Continuer",
                )}
              </button>
            </div>
          </>
        )}
      </form>
    </Dialog>
  );
}
