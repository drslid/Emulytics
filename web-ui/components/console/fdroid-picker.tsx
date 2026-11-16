"use client";

import { useRef, useState } from "react";
import { api, ApiError } from "../../lib/client-api";
import { useLocale } from "../../lib/i18n";
import { localeInfo } from "../../lib/i18n-core";
import { Icon } from "./icons";
import { ErrorNotice } from "./shared";

type Release = { sha256: string; version_name: string; version_code: number; added_at: string };
type StoreApplication = { package_name: string; name: string; versions: Release[] };

export function FDroidPicker({ busy, importing, canSelectPackage, onImport }: {
  busy: boolean;
  importing: boolean;
  canSelectPackage: (packageName: string) => boolean;
  onImport: (packageName: string, sha256: string) => void;
}) {
  const { t, locale } = useLocale();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<StoreApplication[] | null>(null);
  const [packageName, setPackageName] = useState("");
  const [sha256, setSha256] = useState("");
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");
  const sequence = useRef(0);
  const application = results?.find(item => item.package_name === packageName);
  const date = new Intl.DateTimeFormat(localeInfo[locale].intl, { dateStyle: "medium", timeZone: "UTC" });
  const options = application?.versions.map(item => ({
    ...item, label: `${item.version_name} (${item.version_code}) · ${date.format(new Date(item.added_at))}`,
  })) ?? [];
  const labels = new Map<string, number>();
  for (const { label } of options) labels.set(label, (labels.get(label) ?? 0) + 1);
  const release = options.find(item => item.sha256 === sha256) ?? options[0];
  const canSearch = query.trim().length >= 2 && !busy && !searching;

  async function search() {
    if (!canSearch) return;
    const request = ++sequence.current;
    setSearching(true);
    setError("");
    setResults(null);
    try {
      const { items } = await api<{ items: StoreApplication[] }>(`console/applications/fdroid?${new URLSearchParams({ q: query.trim() })}`);
      if (sequence.current !== request) return;
      setResults(items);
      setPackageName(items[0]?.package_name ?? "");
      setSha256("");
    } catch (failure) {
      if (sequence.current !== request) return;
      setError(failure instanceof ApiError && [401, 403].includes(failure.status) ? failure.message : t("F-Droid est indisponible. Réessayez."));
    } finally {
      if (sequence.current === request) setSearching(false);
    }
  }

  return <div className="emulator-store">
    <label className="emulator-store-query">
      {t("Rechercher sur F-Droid")}
      <input type="search" value={query} maxLength={100} disabled={busy}
        placeholder={t("Nom ou identifiant de l’application")}
        onChange={event => {
          sequence.current++;
          setQuery(event.target.value);
          setResults(null);
          setError("");
          setSearching(false);
        }}
        onKeyDown={event => {
          if (event.key === "Enter" && !event.nativeEvent.isComposing) {
            event.preventDefault();
            void search();
          }
        }} />
    </label>
    <button type="button" className="button button--secondary emulator-store-submit" disabled={!canSearch} onClick={() => void search()}>
      <Icon name="search" size={16} />{t("Rechercher un APK")}
    </button>
    {searching && <p className="small-copy" role="status">{t("Recherche sur F-Droid…")}</p>}
    {error && <ErrorNotice message={error} />}
    {results?.length === 0 && <p className="small-copy" role="status">{t("Aucun APK trouvé. Essayez un autre nom ou identifiant.")}</p>}
    {application && release && <div className="emulator-store-results">
      <label>{t("Application F-Droid")}
        <select value={packageName} disabled={busy} onChange={event => { setPackageName(event.target.value); setSha256(""); }}>
          {results?.map(item => <option key={item.package_name} value={item.package_name}>{item.name} · {item.package_name}</option>)}
        </select>
      </label>
      <label>{t("Version et date d’ajout")}
        <select value={release.sha256} disabled={busy} onChange={event => setSha256(event.target.value)}>
          {options.map(item => <option key={item.sha256} value={item.sha256}>
            {labels.get(item.label) === 1 ? item.label : `${item.label} · ${item.sha256.slice(0, 8)}`}
          </option>)}
        </select>
      </label>
      <button type="button" className="button button--secondary" disabled={busy || !canSelectPackage(packageName)}
        onClick={() => onImport(packageName, release.sha256)}>
        <Icon name="plus" size={16} />{t(importing ? "Importation en cours…" : "Importer depuis F-Droid")}
      </button>
    </div>}
  </div>;
}
