"use client";

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
  type RefObject,
} from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "../../lib/client-api";
import type { User } from "../../lib/console-types";
import { useLocale, useT } from "../../lib/i18n";
import { localeInfo } from "../../lib/i18n-core";
import { LanguageSelector } from "../language-selector";
import { Icon } from "./icons";
import { Security } from "./security";
import { Dialog, Empty, ErrorNotice, date } from "./shared";

const roles = ["admin", "builder", "operator", "viewer", "auditor"] as const;
const labels = {
  admin: "Admin",
  builder: "Builder",
  operator: "Operator",
  viewer: "Viewer",
  auditor: "Auditor",
};
const descriptions = {
  admin: "Gère toute la solution, les utilisateurs et la sécurité.",
  builder: "Crée, publie, lance et planifie des parcours.",
  operator: "Gère les appareils, lance et planifie les parcours publiés.",
  viewer: "Consulte les appareils, les résultats et le monitoring.",
  auditor:
    "Consulte les résultats, le monitoring et les journaux de traçabilité.",
};
type LocalUser = User & {
  totp_enabled: boolean;
  password_change_required: boolean;
  created_at: string;
  last_login_at: string | null;
  password_changed_at: string | null;
  active_sessions: number;
  recovery_codes_remaining: number;
};
type UserPage = {
  items: LocalUser[];
  total: number;
  limit: number;
  offset: number;
};
type Credential = { user: LocalUser; temporary_password: string };
type SecurityAction =
  | "reset-password"
  | "reset-2fa"
  | "revoke-sessions"
  | "force-password-change";
type Modal =
  | { kind: "create" }
  | { kind: "detail" | "edit"; target: LocalUser }
  | { kind: SecurityAction; target: LocalUser }
  | { kind: "secret"; credential: Credential };
type Identity = { first_name: string; last_name: string; email: string };
const identityOf = (user?: User): Identity => ({
  first_name: user?.first_name ?? "",
  last_name: user?.last_name ?? "",
  email: user?.email ?? "",
});
function errorCode(failure: unknown): string | undefined {
  return failure instanceof ApiError &&
    "code" in failure &&
    typeof failure.code === "string"
    ? failure.code
    : undefined;
}

export function Users({ user }: { user: User }) {
  const t = useT(),
    { locale } = useLocale(),
    router = useRouter();
  const [page, setPage] = useState<UserPage | null>(null),
    [offset, setOffset] = useState(0),
    [busy, setBusy] = useState(true),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [filters, setFilters] = useState({
    q: "",
    role: "",
    active: "all",
    two_factor: "all",
    onboarding: "all",
  });
  const [modal, setModal] = useState<Modal | null>(null);
  const sequence = useRef(0);
  const load = useCallback(async () => {
    const request = ++sequence.current;
    setBusy(true);
    try {
      const query = new URLSearchParams({
        limit: "50",
        offset: String(offset),
        ...filters,
      });
      if (!filters.role) query.delete("role");
      const result = await api<UserPage>(`console/users?${query}`);
      if (request === sequence.current) {
        setPage(result);
        setError("");
      }
    } catch (failure) {
      if (request === sequence.current) {
        setError((failure as Error).message);
        setPage(null);
      }
    } finally {
      if (request === sequence.current) setBusy(false);
    }
  }, [filters, offset]);
  useEffect(() => {
    const timer = setTimeout(() => void load(), 250);
    return () => {
      clearTimeout(timer);
      sequence.current++;
    };
  }, [load]);
  function filter(key: keyof typeof filters, value: string) {
    setBusy(true);
    setOffset(0);
    setFilters((current) => ({ ...current, [key]: value }));
  }
  function changed(target?: LocalUser) {
    if (target?.id === user.id) router.refresh();
    setModal(target ? { kind: "detail", target } : null);
    setNotice(t("Utilisateur mis à jour."));
    void load();
  }
  function credentialReady(credential: Credential) {
    setModal({ kind: "secret", credential });
    void load();
  }
  return (
    <div className="section-stack">
      <section className="surface users-directory">
        <div className="surface-heading">
          <div>
            <h2>{t("Utilisateurs locaux")}</h2>
            <p>{t("Identité, accès et sécurité de chaque compte.")}</p>
          </div>
          <button
            className="button button--primary"
            onClick={() => {
              setNotice("");
              setModal({ kind: "create" });
            }}
          >
            <Icon name="plus" size={18} />
            {t("Ajouter un utilisateur")}
          </button>
        </div>
        {error && <ErrorNotice message={error} />}{" "}
        {notice && (
          <p className="notice notice--success" role="status">
            {notice}
          </p>
        )}
        <div className="table-toolbar users-search">
          <label className="search-field">
            <Icon name="search" size={18} />
            <input
              value={filters.q}
              maxLength={320}
              onChange={(e) => filter("q", e.target.value)}
              placeholder={t("Nom, identifiant ou adresse e-mail…")}
              aria-label={t("Rechercher un utilisateur")}
            />
          </label>
          <button
            className="button button--secondary"
            disabled={busy}
            onClick={() => void load()}
          >
            <Icon name="refresh" size={18} />
            {t("Actualiser")}
          </button>
        </div>
        <div className="users-filters">
          <label>
            {t("Rôle")}
            <select
              value={filters.role}
              onChange={(e) => filter("role", e.target.value)}
            >
              <option value="">{t("Tous les rôles")}</option>
              {roles.map((role) => (
                <option value={role} key={role}>
                  {t(labels[role])}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("Accès")}
            <select
              value={filters.active}
              onChange={(e) => filter("active", e.target.value)}
            >
              <option value="all">{t("Tous les comptes")}</option>
              <option value="active">{t("Actif")}</option>
              <option value="inactive">{t("Désactivé")}</option>
            </select>
          </label>
          <label>
            {t("Validation en deux étapes")}
            <select
              value={filters.two_factor}
              onChange={(e) => filter("two_factor", e.target.value)}
            >
              <option value="all">{t("Tous les états")}</option>
              <option value="enabled">{t("Activée")}</option>
              <option value="pending">{t("À activer")}</option>
            </select>
          </label>
          <label>
            {t("Première connexion")}
            <select
              value={filters.onboarding}
              onChange={(e) => filter("onboarding", e.target.value)}
            >
              <option value="all">{t("Tous les états")}</option>
              <option value="required">{t("À finaliser")}</option>
              <option value="ready">{t("Configuration terminée")}</option>
            </select>
          </label>
        </div>
        <div className="users-results-status" aria-live="polite">
          {busy
            ? t("Actualisation…")
            : page
              ? t("{n} utilisateur(s)", { n: page.total })
              : ""}
        </div>
        {!page ? (
          <p className="users-loading" role="status">
            {t(
              error
                ? "La liste des utilisateurs est indisponible."
                : "Chargement…",
            )}
          </p>
        ) : page.items.length ? (
          <div
            className="table-scroll"
            role="region"
            aria-label={t("Liste des utilisateurs")}
            tabIndex={0}
          >
            <table className="data-table users-table">
              <thead>
                <tr>
                  <th>{t("Utilisateur")}</th>
                  <th>{t("Adresse e-mail")}</th>
                  <th>{t("Rôle")}</th>
                  <th>{t("Accès")}</th>
                  <th>{t("Sécurité")}</th>
                  <th>{t("Dernière connexion")}</th>
                  <th>{t("Actions")}</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((item) => (
                  <tr key={item.id}>
                    <td data-label={t("Utilisateur")}>
                      <strong>
                        <bdi>{item.display_name}</bdi>
                      </strong>
                      {item.id === user.id && (
                        <span className="muted"> · {t("Vous")}</span>
                      )}
                      <span className="cell-secondary" dir="ltr">
                        {item.username}
                      </span>
                    </td>
                    <td data-label={t("Adresse e-mail")}>
                      <span dir="ltr">{item.email || t("À compléter")}</span>
                    </td>
                    <td data-label={t("Rôle")}>{t(labels[item.role])}</td>
                    <td data-label={t("Accès")}>
                      <span
                        className={`status-badge status-badge--${item.active ? "green" : "neutral"}`}
                      >
                        {t(item.active ? "Actif" : "Désactivé")}
                      </span>
                      {item.password_change_required && (
                        <span className="cell-secondary">
                          {t("Mot de passe à changer")}
                        </span>
                      )}
                    </td>
                    <td data-label={t("Sécurité")}>
                      <span
                        className={`status-badge status-badge--${item.totp_enabled ? "green" : "amber"}`}
                      >
                        2FA · {t(item.totp_enabled ? "Activée" : "À activer")}
                      </span>
                      <span className="cell-secondary">
                        {t("{n} session(s) active(s)", {
                          n: item.active_sessions ?? 0,
                        })}
                      </span>
                    </td>
                    <td data-label={t("Dernière connexion")}>
                      {item.last_login_at
                        ? date(item.last_login_at, locale)
                        : t("Non renseigné")}
                    </td>
                    <td data-label={t("Actions")}>
                      <button
                        className="button button--secondary button--small"
                        disabled={busy}
                        onClick={() =>
                          setModal({ kind: "detail", target: item })
                        }
                        aria-label={`${t("Gérer")} ${item.display_name}`}
                      >
                        {t("Gérer")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty icon="search" title={t("Aucun utilisateur trouvé")}>
            {t("Modifiez la recherche ou les filtres.")}
          </Empty>
        )}
        {page && (
          <div className="table-footer">
            <span>{t("Recherche sur tous les utilisateurs")}</span>
            <div className="row-actions">
              <button
                className="button button--secondary"
                disabled={busy || offset === 0}
                onClick={() => setOffset(Math.max(0, offset - 50))}
              >
                {t("Précédent")}
              </button>
              <button
                className="button button--secondary"
                disabled={busy || offset + page.items.length >= page.total}
                onClick={() => setOffset(offset + 50)}
              >
                {t("Suivant")}
              </button>
            </div>
          </div>
        )}
      </section>
      <section className="surface">
        <div className="surface-heading">
          <div>
            <h2>{t("Cinq rôles, des droits clairs")}</h2>
            <p>
              {t(
                "Les permissions sont contrôlées par le serveur à chaque action.",
              )}
            </p>
          </div>
        </div>
        <div className="role-grid">
          {roles.map((role) => (
            <div className="role-card" key={role}>
              <strong>{t(labels[role])}</strong>
              <p>{t(descriptions[role])}</p>
            </div>
          ))}
        </div>
      </section>
      {modal?.kind === "create" && (
        <UserEditor
          onClose={() => setModal(null)}
          onCreated={credentialReady}
        />
      )}
      {modal?.kind === "edit" && (
        <UserEditor
          target={modal.target}
          self={modal.target.id === user.id}
          onClose={() => setModal({ kind: "detail", target: modal.target })}
          onSaved={changed}
        />
      )}
      {modal?.kind === "detail" && (
        <UserDetails
          initial={modal.target}
          self={modal.target.id === user.id}
          onClose={() => setModal(null)}
          onEdit={(target) => setModal({ kind: "edit", target })}
          onAction={(kind, target) => setModal({ kind, target })}
        />
      )}
      {modal &&
        [
          "reset-password",
          "reset-2fa",
          "revoke-sessions",
          "force-password-change",
        ].includes(modal.kind) &&
        "target" in modal && (
          <UserSecurityAction
            target={modal.target}
            self={modal.target.id === user.id}
            action={modal.kind as SecurityAction}
            onClose={() => setModal({ kind: "detail", target: modal.target })}
            onCredential={credentialReady}
            onChanged={changed}
          />
        )}
      {modal?.kind === "secret" && (
        <TemporaryCredential
          credential={modal.credential}
          onClose={() =>
            setModal({ kind: "detail", target: modal.credential.user })
          }
        />
      )}
    </div>
  );
}

function RoleSelect({
  value,
  onChange,
}: {
  value: User["role"];
  onChange: (role: User["role"]) => void;
}) {
  const t = useT();
  return (
    <label>
      {t("Rôle")}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as User["role"])}
      >
        {roles.map((role) => (
          <option value={role} key={role}>
            {t(labels[role])}
          </option>
        ))}
      </select>
      <span>{t(descriptions[value])}</span>
    </label>
  );
}

function IdentityFields({
  value,
  onChange,
  emailError,
  emailRef,
  personal = false,
  required = false,
}: {
  value: Identity;
  onChange: (identity: Identity) => void;
  emailError: string;
  emailRef: RefObject<HTMLInputElement | null>;
  personal?: boolean;
  required?: boolean;
}) {
  const t = useT(),
    errorId = useId();
  return (
    <>
      <label>
        {t("Prénom")}
        <input
          name="first_name"
          value={value.first_name}
          onChange={(e) => onChange({ ...value, first_name: e.target.value })}
          required={required}
          maxLength={120}
          autoComplete={personal ? "given-name" : "off"}
          autoFocus
        />
      </label>
      <label>
        {t("Nom")}
        <input
          name="last_name"
          value={value.last_name}
          onChange={(e) => onChange({ ...value, last_name: e.target.value })}
          maxLength={120}
          autoComplete={personal ? "family-name" : "off"}
        />
        <span>{t("Facultatif si vous n’avez qu’un seul nom.")}</span>
      </label>
      <label>
        {t("Adresse e-mail")}
        <input
          ref={emailRef}
          name="email"
          type="text"
          inputMode="email"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          dir="ltr"
          autoComplete={personal ? "email" : "off"}
          value={value.email}
          onChange={(e) => onChange({ ...value, email: e.target.value })}
          required={required}
          maxLength={320}
          aria-invalid={!!emailError}
          aria-describedby={emailError ? errorId : undefined}
        />
        {emailError ? (
          <span id={errorId} className="field-error" role="alert">
            {emailError}
          </span>
        ) : (
          <span>
            {t(
              "Adresse de contact, sans modification de l’identifiant de connexion.",
            )}
          </span>
        )}
      </label>
    </>
  );
}
function cleanIdentity(identity: Identity) {
  return {
    first_name: identity.first_name.trim(),
    last_name: identity.last_name.trim(),
    email: identity.email.trim() || null,
  };
}
function identityFailure(failure: unknown, t: ReturnType<typeof useT>): string {
  const code = errorCode(failure);
  if (code === "last_admin_required")
    return t(
      "Le dernier Admin prêt à se connecter doit être conservé. Un autre Admin doit avoir finalisé son mot de passe et son 2FA avant de modifier cet accès.",
    );
  if (code === "username_in_use")
    return t(
      "Cet identifiant de connexion est déjà utilisé. Choisissez-en un autre.",
    );
  if (code === "self_security_required")
    return t("Gérez votre propre mot de passe et votre 2FA depuis Mon profil.");
  return (failure as Error).message;
}
function emailFailure(failure: unknown, t: ReturnType<typeof useT>): string {
  return errorCode(failure) === "email_in_use"
    ? t("Cette adresse e-mail est déjà utilisée par un autre compte.")
    : errorCode(failure) === "invalid_email"
      ? t("Vérifiez l’adresse e-mail, par exemple nom@example.com.")
      : "";
}

function UserEditor({
  target,
  self = false,
  onClose,
  onCreated,
  onSaved,
}: {
  target?: LocalUser;
  self?: boolean;
  onClose: () => void;
  onCreated?: (value: Credential) => void;
  onSaved?: (value: LocalUser) => void;
}) {
  const t = useT();
  const [identity, setIdentity] = useState(() => identityOf(target)),
    [role, setRole] = useState<User["role"]>(target?.role ?? "viewer"),
    [active, setActive] = useState(target?.active ?? true),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [emailError, setEmailError] = useState("");
  const emailRef = useRef<HTMLInputElement>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    setEmailError("");
    try {
      const identityPayload = cleanIdentity(identity);
      if (target) {
        const updated = await api<LocalUser>(
          `console/users/${target.id}`,
          { ...identityPayload, role, active },
          "PATCH",
        );
        if (self && (target.role !== role || target.active !== active))
          window.location.assign("/connexion");
        else onSaved?.(updated);
      } else {
        const username = String(form.get("username") ?? "").trim();
        onCreated?.(
          await api<Credential>("console/users", {
            ...identityPayload,
            role,
            ...(username ? { username } : {}),
          }),
        );
      }
    } catch (failure) {
      const mail = emailFailure(failure, t);
      if (mail) {
        setEmailError(mail);
        emailRef.current?.focus();
      } else setError(identityFailure(failure, t));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title={t(target ? "Modifier l’utilisateur" : "Ajouter un utilisateur")}
      description={
        target?.username ??
        t(
          "Un mot de passe temporaire sera généré. La première connexion impose son changement et l’activation du 2FA.",
        )
      }
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="dialog-form" onSubmit={submit}>
        {error && <ErrorNotice message={error} />}
        <IdentityFields
          value={identity}
          onChange={setIdentity}
          emailError={emailError}
          emailRef={emailRef}
          required={!target}
        />
        {!target && (
          <details className="user-login-options">
            <summary>{t("Personnaliser l’identifiant de connexion")}</summary>
            <label>
              {t("Identifiant de connexion")}
              <input name="username" maxLength={120} autoComplete="off" />
              <span>
                {t(
                  "Laissez ce champ vide pour générer un identifiant automatiquement.",
                )}
              </span>
            </label>
          </details>
        )}
        <RoleSelect value={role} onChange={setRole} />
        {target && (
          <>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={active}
                onChange={(e) => setActive(e.target.checked)}
              />
              {t("Compte actif")}
            </label>
            <p className="small-copy">
              {t(
                "Changer le rôle ou désactiver un compte ferme ses sessions immédiatement.",
              )}
            </p>
            {self && (
              <div className="notice notice--info">
                {t(
                  "Vous modifiez votre propre compte. Un changement de droits vous demandera de vous reconnecter.",
                )}
              </div>
            )}
          </>
        )}
        {!target && error && (
          <p className="small-copy">
            {t(
              "Si la réponse a été interrompue, vérifiez la liste des utilisateurs. Un administrateur peut générer un nouveau mot de passe temporaire.",
            )}
          </p>
        )}
        <div className="dialog-footer">
          <button
            type="button"
            className="button button--secondary"
            disabled={busy}
            onClick={onClose}
          >
            {t("Annuler")}
          </button>
          <button className="button button--primary" disabled={busy}>
            {t(
              busy
                ? "Enregistrement…"
                : target
                  ? "Enregistrer"
                  : "Créer l’utilisateur",
            )}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function UserDetails({
  initial,
  self,
  onClose,
  onEdit,
  onAction,
}: {
  initial: LocalUser;
  self: boolean;
  onClose: () => void;
  onEdit: (user: LocalUser) => void;
  onAction: (action: SecurityAction, user: LocalUser) => void;
}) {
  const t = useT(),
    { locale } = useLocale();
  const [target, setTarget] = useState(initial),
    [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    void api<LocalUser>(`console/users/${initial.id}`)
      .then((user) => {
        if (!cancelled) setTarget(user);
      })
      .catch((failure) => {
        if (!cancelled) setError((failure as Error).message);
      });
    return () => {
      cancelled = true;
    };
  }, [initial.id]);
  const value = (value: string | null | undefined) => value || t("À compléter"),
    timestamp = (value: string | null | undefined) =>
      value ? date(value, locale) : t("Non renseigné");
  return (
    <Dialog
      wide
      title={target.display_name}
      description={target.username}
      onClose={onClose}
    >
      <div className="user-detail-body">
        {error && <ErrorNotice message={error} />}
        <section aria-labelledby="user-identity-heading">
          <div className="section-heading">
            <h3 id="user-identity-heading">{t("Identité et contact")}</h3>
            <button
              className="button button--secondary button--small"
              onClick={() => onEdit(target)}
            >
              {t("Modifier")}
            </button>
          </div>
          <dl className="user-facts">
            <div>
              <dt>{t("Prénom")}</dt>
              <dd>
                <bdi>{value(target.first_name)}</bdi>
              </dd>
            </div>
            <div>
              <dt>{t("Nom")}</dt>
              <dd>
                <bdi>{value(target.last_name)}</bdi>
              </dd>
            </div>
            <div className="user-fact-wide">
              <dt>{t("Adresse e-mail")}</dt>
              <dd dir="ltr">{value(target.email)}</dd>
            </div>
          </dl>
          <p className="small-copy">
            {t(
              "L’adresse e-mail est une coordonnée de contact. Elle n’est pas vérifiée automatiquement.",
            )}
          </p>
        </section>
        <section aria-labelledby="user-access-heading">
          <h3 id="user-access-heading">{t("Accès au compte")}</h3>
          <dl className="user-facts">
            <div>
              <dt>{t("Rôle")}</dt>
              <dd>{t(labels[target.role])}</dd>
            </div>
            <div>
              <dt>{t("Accès")}</dt>
              <dd>{t(target.active ? "Actif" : "Désactivé")}</dd>
            </div>
            <div>
              <dt>{t("Compte créé")}</dt>
              <dd>{timestamp(target.created_at)}</dd>
            </div>
            <div>
              <dt>{t("Dernière connexion")}</dt>
              <dd>{timestamp(target.last_login_at)}</dd>
            </div>
          </dl>
          <p className="small-copy">{t(descriptions[target.role])}</p>
        </section>
        <section aria-labelledby="user-security-heading">
          <h3 id="user-security-heading">{t("Sécurité")}</h3>
          <dl className="user-facts">
            <div>
              <dt>{t("Validation en deux étapes")}</dt>
              <dd>{t(target.totp_enabled ? "Activée" : "À activer")}</dd>
            </div>
            <div>
              <dt>{t("Mot de passe")}</dt>
              <dd>
                {t(
                  target.password_change_required
                    ? "Mot de passe à changer"
                    : "Mot de passe personnel",
                )}
              </dd>
            </div>
            <div>
              <dt>{t("Mot de passe modifié")}</dt>
              <dd>{timestamp(target.password_changed_at)}</dd>
            </div>
            <div>
              <dt>{t("Sessions actives")}</dt>
              <dd>{target.active_sessions ?? 0}</dd>
            </div>
            <div>
              <dt>{t("Codes disponibles")}</dt>
              <dd>{target.recovery_codes_remaining ?? 0}</dd>
            </div>
          </dl>
          {self ? (
            <div className="notice notice--info">
              <span>
                {t(
                  "Gérez votre propre mot de passe et votre 2FA depuis Mon profil.",
                )}
              </span>
              <a href="/profil#securite">{t("Mon profil")}</a>
            </div>
          ) : (
            <div className="user-security-actions">
              <button
                className="button button--secondary"
                onClick={() => onAction("reset-password", target)}
              >
                {t("Réinitialiser le mot de passe")}
              </button>
              <button
                className="button button--secondary"
                onClick={() => onAction("reset-2fa", target)}
              >
                {t("Réinitialiser le 2FA")}
              </button>
              <button
                className="button button--secondary"
                disabled={target.password_change_required}
                onClick={() => onAction("force-password-change", target)}
              >
                {t("Exiger un nouveau mot de passe")}
              </button>
            </div>
          )}
          <button
            className="text-button user-revoke"
            onClick={() => onAction("revoke-sessions", target)}
          >
            <Icon name="logout" size={17} />
            {t("Fermer toutes les sessions")}
          </button>
        </section>
        <div className="dialog-footer">
          <button className="button button--secondary" onClick={onClose}>
            {t("Fermer")}
          </button>
        </div>
      </div>
    </Dialog>
  );
}

function UserSecurityAction({
  target,
  self,
  action,
  onClose,
  onCredential,
  onChanged,
}: {
  target: LocalUser;
  self: boolean;
  action: SecurityAction;
  onClose: () => void;
  onCredential: (value: Credential) => void;
  onChanged: (value?: LocalUser) => void;
}) {
  const t = useT();
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const actions = {
    "reset-password": {
      title: "Réinitialiser le mot de passe ?",
      copy: "Les sessions seront fermées. Un mot de passe temporaire remplacera le mot de passe actuel et devra être changé à la prochaine connexion.",
    },
    "reset-2fa": {
      title: "Réinitialiser le 2FA ?",
      copy: "Les sessions et les codes de secours seront révoqués. Le mot de passe reste requis et une nouvelle application d’authentification devra être activée.",
    },
    "revoke-sessions": {
      title: "Fermer toutes les sessions ?",
      copy: "Toutes les sessions de cet utilisateur seront fermées. Son mot de passe et son 2FA restent inchangés.",
    },
    "force-password-change": {
      title: "Exiger un nouveau mot de passe ?",
      copy: "Les sessions seront fermées. L’utilisateur devra remplacer son mot de passe à sa prochaine connexion, sans recevoir de mot de passe temporaire.",
    },
  };
  const { title, copy } = actions[action];
  async function apply() {
    setBusy(true);
    setError("");
    try {
      if (action === "reset-password")
        onCredential(
          await api<Credential>(`console/users/${target.id}/${action}`, {}),
        );
      else if (action === "revoke-sessions") {
        const result = await api<{ user: LocalUser; revoked_sessions: number }>(
          `console/users/${target.id}/${action}`,
          {},
        );
        if (self) window.location.assign("/connexion");
        else onChanged(result.user);
      } else
        onChanged(
          await api<LocalUser>(`console/users/${target.id}/${action}`, {}),
        );
    } catch (failure) {
      setError(identityFailure(failure, t));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title={t(title)}
      description={target.display_name}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <div className="dialog-form">
        {error && <ErrorNotice message={error} />}
        <p>{t(copy)}</p>
        {self && (
          <div className="notice notice--warning">
            {t(
              "Votre propre session sera fermée. Vous devrez vous reconnecter.",
            )}
          </div>
        )}
        <div className="dialog-footer">
          <button
            className="button button--secondary"
            disabled={busy}
            onClick={onClose}
          >
            {t("Annuler")}
          </button>
          <button
            className="button button--primary"
            disabled={busy}
            onClick={() => void apply()}
          >
            {t(busy ? "Enregistrement…" : "Confirmer")}
          </button>
        </div>
      </div>
    </Dialog>
  );
}

function TemporaryCredential({
  credential,
  onClose,
}: {
  credential: Credential;
  onClose: () => void;
}) {
  const t = useT();
  const [copied, setCopied] = useState(false),
    [error, setError] = useState("");
  async function copy() {
    try {
      await navigator.clipboard.writeText(
        `${credential.user.username}\n${credential.temporary_password}`,
      );
      setCopied(true);
    } catch {
      setError(
        t(
          "La copie n’est pas disponible. Sélectionnez les informations pour les copier.",
        ),
      );
    }
  }
  return (
    <Dialog
      title={t("Accès temporaire prêt")}
      description={t(
        "Ce mot de passe est affiché une seule fois. Transmettez-le à la personne concernée avant de fermer.",
      )}
      onClose={onClose}
    >
      <div className="dialog-form">
        {error && <ErrorNotice message={error} />}
        <label>
          {t("Identifiant de connexion")}
          <input
            value={credential.user.username}
            readOnly
            dir="ltr"
            autoComplete="off"
          />
        </label>
        <label>
          {t("Mot de passe temporaire")}
          <input
            className="one-time-secret"
            value={credential.temporary_password}
            readOnly
            dir="ltr"
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <div className="notice notice--info">
          {t(
            credential.user.totp_enabled
              ? "À sa prochaine connexion, l’utilisateur changera ce mot de passe. Son application d’authentification reste active."
              : "À sa première connexion, l’utilisateur changera ce mot de passe puis activera son application d’authentification.",
          )}
        </div>
        <div className="dialog-footer">
          <button
            className="button button--secondary"
            onClick={() => void copy()}
          >
            {t(copied ? "Copié" : "Copier les accès")}
          </button>
          <button className="button button--primary" onClick={onClose}>
            {t("J’ai conservé les accès")}
          </button>
        </div>
      </div>
    </Dialog>
  );
}

export function Profile({
  user,
  onLogout,
}: {
  user: User;
  onLogout: () => void;
}) {
  const t = useT(),
    { locale } = useLocale(),
    router = useRouter();
  const [editing, setEditing] = useState(false),
    [notice, setNotice] = useState("");
  return (
    <div className="section-stack">
      <div className="security-layout">
        <section className="surface security-card">
          <div className="profile-identity-heading">
            <span className="secure-symbol secure-symbol--large">
              <Icon name="users" size={32} />
            </span>
            <button
              className="button button--secondary button--small"
              onClick={() => setEditing(true)}
            >
              {t("Modifier mes informations")}
            </button>
          </div>
          <h2>
            <bdi>{user.display_name || user.username}</bdi>
          </h2>
          <p className="muted" dir="ltr">
            {user.username}
          </p>
          {notice && (
            <p className="notice notice--success" role="status">
              {notice}
            </p>
          )}
          <dl className="user-facts profile-facts">
            <div>
              <dt>{t("Prénom")}</dt>
              <dd>
                <bdi>{user.first_name || t("À compléter")}</bdi>
              </dd>
            </div>
            <div>
              <dt>{t("Nom")}</dt>
              <dd>
                <bdi>{user.last_name || t("À compléter")}</bdi>
              </dd>
            </div>
            <div className="user-fact-wide">
              <dt>{t("Adresse e-mail")}</dt>
              <dd dir="ltr">{user.email || t("À compléter")}</dd>
            </div>
          </dl>
          <div className="security-line">
            <span>{t("Rôle")}</span>
            <strong>{t(labels[user.role])}</strong>
          </div>
          <p>{t(descriptions[user.role])}</p>
        </section>
        <aside className="surface security-card">
          <h2>{t("Préférences")}</h2>
          <p>
            {t(
              "La langue est détectée à partir de votre navigateur. Vous pouvez choisir une autre langue à tout moment.",
            )}
          </p>
          <div className="security-line">
            <span>{t("Langue")}</span>
            <LanguageSelector />
          </div>
          <p className="muted">{localeInfo[locale].name}</p>
          <p className="small-copy">
            {t(
              "L’adresse e-mail est une coordonnée de contact. Elle n’est pas vérifiée automatiquement.",
            )}
          </p>
        </aside>
      </div>
      <section
        id="securite"
        aria-labelledby="profile-security-title"
        style={{ scrollMarginTop: 24 }}
      >
        <div className="section-heading">
          <h2 id="profile-security-title">{t("Sécurité du compte")}</h2>
        </div>
        <Security user={user} onLogout={onLogout} />
      </section>
      {editing && (
        <ProfileEditor
          user={user}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            setNotice(t("Vos informations ont été mises à jour."));
            router.refresh();
          }}
        />
      )}
    </div>
  );
}
function ProfileEditor({
  user,
  onClose,
  onSaved,
}: {
  user: User;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useT();
  const [identity, setIdentity] = useState(() => identityOf(user)),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [emailError, setEmailError] = useState("");
  const emailRef = useRef<HTMLInputElement>(null);
  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setEmailError("");
    try {
      await api<{ user: User }>(
        "console/account/profile",
        cleanIdentity(identity),
        "PATCH",
      );
      onSaved();
    } catch (failure) {
      const mail = emailFailure(failure, t);
      if (mail) {
        setEmailError(mail);
        emailRef.current?.focus();
      } else setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title={t("Modifier mes informations")}
      description={user.username}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="dialog-form" onSubmit={save}>
        {error && <ErrorNotice message={error} />}
        <IdentityFields
          value={identity}
          onChange={setIdentity}
          emailError={emailError}
          emailRef={emailRef}
          personal
        />
        <div className="dialog-footer">
          <button
            type="button"
            className="button button--secondary"
            disabled={busy}
            onClick={onClose}
          >
            {t("Annuler")}
          </button>
          <button className="button button--primary" disabled={busy}>
            {t(busy ? "Enregistrement…" : "Enregistrer")}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
