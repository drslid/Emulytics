"use client";
import { useEffect, useState } from "react";
import { api } from "../../lib/client-api";
import { useLocale, useT } from "../../lib/i18n";
import type { Page } from "../../lib/console-types";
import { date, ErrorNotice } from "./shared";
import { Icon } from "./icons";
type Log = {
  id: string;
  occurred_at: string;
  severity: string;
  category: string;
  action: string;
  entity_id: string | null;
  actor: string | null;
};
export function Logs() {
  const t = useT(),
    { locale } = useLocale();
  const [items, setItems] = useState<Log[]>([]),
    [total, setTotal] = useState(0),
    [offset, setOffset] = useState(0),
    [q, setQ] = useState(""),
    [category, setCategory] = useState(""),
    [severity, setSeverity] = useState(""),
    [error, setError] = useState(""),
    [updated, setUpdated] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const result = await api<Page<Log>>(
          `console/logs?${new URLSearchParams({ limit: "50", offset: String(offset), q, category, severity })}`,
        );
        if (!cancelled) {
          setItems(result.items);
          setTotal(result.total ?? result.items.length);
          setUpdated(new Date().toISOString());
          setError("");
        }
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    }
    const delay = setTimeout(() => void load(), 250);
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, 5000);
    return () => {
      cancelled = true;
      clearTimeout(delay);
      clearInterval(timer);
    };
  }, [offset, q, category, severity]);
  return (
    <>
      {error && <ErrorNotice message={error} />}
      <div className="section-heading">
        <div>
          <h2>{t("Journal des événements")}</h2>
          <p>
            {t(
              "Retrouvez les actions des utilisateurs et les événements d’exécution, sans mots de passe ni codes de sécurité.",
            )}
          </p>
        </div>
        {updated && (
          <span className="muted">
            {t("Mis à jour")} {date(updated, locale)}
          </span>
        )}
      </div>
      <section className="surface">
        <div className="table-toolbar log-filters">
          <label className="search-field">
            <Icon name="search" />
            <input
              aria-label={t("Rechercher dans le journal")}
              value={q}
              maxLength={128}
              placeholder={t("Action, utilisateur ou identifiant…")}
              onChange={(e) => {
                setQ(e.target.value);
                setOffset(0);
              }}
            />
          </label>
          <label>
            {t("Catégorie")}
            <select
              value={category}
              onChange={(e) => {
                setCategory(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">{t("Toutes")}</option>
              <option value="access">{t("Accès")}</option>
              <option value="security">{t("Sécurité")}</option>
              <option value="execution">{t("Exécution")}</option>
              <option value="automation">{t("Automatisation")}</option>
              <option value="control">{t("Commandes")}</option>
            </select>
          </label>
          <label>
            {t("Niveau")}
            <select
              value={severity}
              onChange={(e) => {
                setSeverity(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">{t("Tous")}</option>
              <option value="info">{t("Information")}</option>
              <option value="warning">{t("Avertissement")}</option>
              <option value="error">{t("Erreur")}</option>
            </select>
          </label>
        </div>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("Date")}</th>
                <th>{t("Niveau")}</th>
                <th>{t("Événement")}</th>
                <th>{t("Utilisateur")}</th>
                <th>{t("Élément concerné")}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>{date(item.occurred_at, locale)}</td>
                  <td>
                    <span
                      className={`status-badge status-badge--${item.severity === "error" ? "red" : item.severity === "warning" ? "amber" : "neutral"}`}
                    >
                      {t(
                        item.severity === "error"
                          ? "Erreur"
                          : item.severity === "warning"
                            ? "Avertissement"
                            : "Information",
                      )}
                    </span>
                  </td>
                  <td>
                    <code dir="ltr">{item.action}</code>
                    <small className="table-subline">
                      {t(
                        item.category === "access"
                          ? "Accès"
                          : item.category === "security"
                            ? "Sécurité"
                            : item.category === "execution"
                              ? "Exécution"
                              : item.category === "automation"
                                ? "Automatisation"
                                : "Commandes",
                      )}
                    </small>
                  </td>
                  <td>{item.actor ?? "—"}</td>
                  <td>
                    <code dir="ltr">{item.entity_id ?? "—"}</code>
                  </td>
                </tr>
              ))}
              {!items.length && (
                <tr>
                  <td colSpan={5} className="table-empty">
                    {t("Aucun événement pour ces filtres.")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="table-footer">
          <span>{t("{n} événements", { n: total })}</span>
          <div className="row-actions">
            <button
              className="button button--secondary"
              disabled={!offset}
              onClick={() => setOffset(Math.max(0, offset - 50))}
            >
              {t("Précédent")}
            </button>
            <button
              className="button button--secondary"
              disabled={offset + 50 >= total}
              onClick={() => setOffset(offset + 50)}
            >
              {t("Suivant")}
            </button>
          </div>
        </div>
      </section>
    </>
  );
}
