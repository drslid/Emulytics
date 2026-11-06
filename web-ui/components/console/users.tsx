"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import Link from "next/link";
import { api, ApiError } from "../../lib/client-api";
import type { User } from "../../lib/console-types";
import { useLocale, useT } from "../../lib/i18n";
import { localeInfo } from "../../lib/i18n-core";
import { LanguageSelector } from "../language-selector";
import { Icon } from "./icons";
import { Dialog, Empty, ErrorNotice } from "./shared";

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
};
type UserPage = {
  items: LocalUser[];
  total: number;
  limit: number;
  offset: number;
};
type Credential = { user: LocalUser; temporary_password: string };
type Modal =
  | { kind: "create" }
  | { kind: "edit" | "reset-password" | "reset-2fa"; target: LocalUser }
  | { kind: "secret"; credential: Credential };

export function Users({ user }: { user: User }) {
  const t = useT();
  const [page, setPage] = useState<UserPage | null>(null),
    [offset, setOffset] = useState(0);
  const [error, setError] = useState(""),
    [search, setSearch] = useState(""),
    [busy, setBusy] = useState(false);
  const [modal, setModal] = useState<Modal | null>(null),
    [notice, setNotice] = useState("");
  const sequence = useRef(0);
  const load = useCallback(async () => {
    const request = ++sequence.current;
    setBusy(true);
    setError("");
    try {
      const result = await api<UserPage>(
        `console/users?limit=50&offset=${offset}`,
      );
      if (request === sequence.current) setPage(result);
    } catch (failure) {
      if (request === sequence.current) setError((failure as Error).message);
    } finally {
      if (request === sequence.current) setBusy(false);
    }
  }, [offset]);
  useEffect(() => {
    void load();
    return () => {
      sequence.current++;
    };
  }, [load]);
  function credentialReady(credential: Credential) {
    setModal({ kind: "secret", credential });
    if (credential.user.id !== user.id) void load();
  }
  function changed() {
    setModal(null);
    setNotice(t("Utilisateur mis à jour."));
    void load();
  }
  const items =
    page?.items.filter((item) =>
      `${item.display_name} ${item.username} ${t(labels[item.role])}`
        .toLocaleLowerCase()
        .includes(search.toLocaleLowerCase().trim()),
    ) ?? [];
  return (
    <div className="section-stack">
      <section className="surface">
        <div className="surface-heading">
          <div>
            <h2>{t("Utilisateurs locaux")}</h2>
            <p>{t("Attribuez à chacun les droits utiles à son travail.")}</p>
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
        {error && <ErrorNotice message={error} />}
        {notice && (
          <p className="notice notice--success" role="status">
            {notice}
          </p>
        )}
        <div className="table-toolbar">
          <label className="search-field">
            <Icon name="search" size={18} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t("Rechercher un utilisateur")}
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
        {!page && busy ? (
          <p className="muted" role="status">
            {t("Chargement…")}
          </p>
        ) : items.length ? (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("Utilisateur")}</th>
                  <th>{t("Rôle")}</th>
                  <th>{t("Accès")}</th>
                  <th>{t("Validation en deux étapes")}</th>
                  <th>{t("Actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <strong>{item.display_name}</strong>
                      {item.id === user.id && (
                        <span className="muted"> · {t("Vous")}</span>
                      )}
                      <span className="cell-secondary" dir="ltr">
                        {item.username}
                      </span>
                    </td>
                    <td>{t(labels[item.role])}</td>
                    <td>
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
                    <td>{t(item.totp_enabled ? "Activée" : "À activer")}</td>
                    <td>
                      <div className="row-actions">
                        <button
                          className="button button--secondary"
                          aria-label={`${t("Modifier")} ${item.display_name}`}
                          onClick={() =>
                            setModal({ kind: "edit", target: item })
                          }
                        >
                          {t("Modifier")}
                        </button>
                        <details className="user-actions">
                          <summary>{t("Réinitialiser")}</summary>
                          <div className="row-actions">
                            <button
                              className="text-button"
                              onClick={() =>
                                setModal({
                                  kind: "reset-password",
                                  target: item,
                                })
                              }
                            >
                              {t("Mot de passe")}
                            </button>
                            <button
                              className="text-button"
                              onClick={() =>
                                setModal({ kind: "reset-2fa", target: item })
                              }
                            >
                              {t("Validation en deux étapes")}
                            </button>
                          </div>
                        </details>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty icon="search" title={t("Aucun utilisateur trouvé")}>
            {t("Essayez un autre nom.")}
          </Empty>
        )}
        {page && (
          <div className="table-footer">
            <span>
              {t("{n} utilisateur(s)", { n: page.total })} ·{" "}
              {t("Recherche sur cette page")}
            </span>
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
        <CreateUser
          onClose={() => setModal(null)}
          onCreated={credentialReady}
        />
      )}
      {modal?.kind === "edit" && (
        <EditUser
          target={modal.target}
          self={modal.target.id === user.id}
          onClose={() => setModal(null)}
          onSaved={changed}
        />
      )}
      {(modal?.kind === "reset-password" || modal?.kind === "reset-2fa") && (
        <ResetUser
          target={modal.target}
          action={modal.kind}
          onClose={() => setModal(null)}
          onCredential={credentialReady}
          onReset={changed}
        />
      )}
      {modal?.kind === "secret" && (
        <TemporaryCredential
          credential={modal.credential}
          onClose={() => {
            const own = modal.credential.user.id === user.id;
            setModal(null);
            if (own) window.location.assign("/connexion");
          }}
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
  onChange: (value: User["role"]) => void;
}) {
  const t = useT();
  return (
    <label>
      {t("Rôle")}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value as User["role"])}
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

function CreateUser({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (credential: Credential) => void;
}) {
  const t = useT();
  const [role, setRole] = useState<User["role"]>("viewer"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      onCreated(
        await api<Credential>("console/users", {
          username: String(values.get("name")).trim(),
          role,
        }),
      );
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title={t("Ajouter un utilisateur")}
      description={t(
        "Un mot de passe temporaire sera généré. La première connexion impose son changement et l’activation du 2FA.",
      )}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="dialog-form" onSubmit={submit}>
        {error && (
          <>
            <ErrorNotice message={error} />
            <p className="muted">
              {t(
                "Si la réponse a été interrompue, vérifiez la liste des utilisateurs. Un administrateur peut générer un nouveau mot de passe temporaire.",
              )}
            </p>
          </>
        )}
        <label>
          {t("Nom de l’utilisateur")}
          <input
            name="name"
            required
            maxLength={120}
            autoComplete="off"
            placeholder={t("Ex. Camille Dupont")}
            autoFocus
          />
          <span>
            {t(
              "Les espaces et accents sont acceptés. L’identifiant de connexion est généré automatiquement.",
            )}
          </span>
        </label>
        <RoleSelect value={role} onChange={setRole} />
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
            {t(busy ? "Création en cours…" : "Créer l’utilisateur")}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function EditUser({
  target,
  self,
  onClose,
  onSaved,
}: {
  target: LocalUser;
  self: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useT();
  const [role, setRole] = useState(target.role),
    [active, setActive] = useState(target.active),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      await api(
        `console/users/${target.id}`,
        {
          display_name: String(values.get("display_name")).trim(),
          role,
          active,
        },
        "PATCH",
      );
      onSaved();
    } catch (failure) {
      setError(
        failure instanceof ApiError && failure.status === 409
          ? t(
              "Le dernier Admin actif doit être conservé. Ajoutez un autre Admin avant de modifier cet accès.",
            )
          : (failure as Error).message,
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title={t("Modifier l’utilisateur")}
      description={target.username}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="dialog-form" onSubmit={submit}>
        {error && <ErrorNotice message={error} />}
        <label>
          {t("Nom affiché")}
          <input
            name="display_name"
            defaultValue={target.display_name}
            required
            maxLength={120}
            autoFocus
          />
        </label>
        <RoleSelect value={role} onChange={setRole} />
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={active}
            onChange={(event) => setActive(event.target.checked)}
          />
          {t("Compte actif")}
        </label>
        <p className="muted">
          {t(
            "Changer le rôle ou désactiver un compte ferme ses sessions immédiatement.",
          )}
        </p>
        {self && (
          <p className="notice notice--info">
            {t(
              "Vous modifiez votre propre compte. Un changement de droits vous demandera de vous reconnecter.",
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
            {t(busy ? "Enregistrement…" : "Enregistrer")}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function ResetUser({
  target,
  action,
  onClose,
  onCredential,
  onReset,
}: {
  target: LocalUser;
  action: "reset-password" | "reset-2fa";
  onClose: () => void;
  onCredential: (credential: Credential) => void;
  onReset: () => void;
}) {
  const t = useT();
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const password = action === "reset-password";
  async function reset() {
    setBusy(true);
    setError("");
    try {
      if (password)
        onCredential(
          await api<Credential>(
            `console/users/${target.id}/reset-password`,
            {},
          ),
        );
      else {
        await api(`console/users/${target.id}/reset-2fa`, {});
        onReset();
      }
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title={t(
        password ? "Réinitialiser le mot de passe ?" : "Réinitialiser le 2FA ?",
      )}
      description={target.display_name}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <div className="dialog-form">
        {error && <ErrorNotice message={error} />}
        <p>
          {t(
            password
              ? "Les sessions seront fermées. Un mot de passe temporaire remplacera le mot de passe actuel et devra être changé à la prochaine connexion."
              : "Les sessions et les codes de secours seront révoqués. Le mot de passe reste requis et une nouvelle application d’authentification devra être activée.",
          )}
        </p>
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
            onClick={() => void reset()}
          >
            {t(busy ? "Réinitialisation…" : "Confirmer la réinitialisation")}
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
            "À sa première connexion, l’utilisateur changera ce mot de passe puis activera son application d’authentification.",
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

export function Profile({ user }: { user: User }) {
  const t = useT();
  const { locale } = useLocale();
  return (
    <div className="security-layout">
      <section className="surface security-card">
        <span className="secure-symbol secure-symbol--large">
          <Icon name="shield" size={32} />
        </span>
        <h2>{user.display_name}</h2>
        <p className="muted" dir="ltr">
          {user.username}
        </p>
        <div className="security-line">
          <span>{t("Rôle")}</span>
          <strong>{t(labels[user.role])}</strong>
        </div>
        <p>{t(descriptions[user.role])}</p>
        <div className="security-line">
          <span>{t("Validation en deux étapes")}</span>
          <span className="status-badge status-badge--green">
            <Icon name="check" size={14} />
            {t("Activée")}
          </span>
        </div>
        <Link className="button button--secondary" href="/securite">
          <Icon name="shield" size={18} />
          {t("Sécurité du compte")}
        </Link>
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
      </aside>
    </div>
  );
}
