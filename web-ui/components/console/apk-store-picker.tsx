"use client";

import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../lib/client-api";
import { useLocale } from "../../lib/i18n";
import { localeInfo } from "../../lib/i18n-core";
import { Icon } from "./icons";
import { ErrorNotice } from "./shared";

export type ApkStore = "fdroid" | "aptoide";
export const apkStoreNames = { fdroid: "F-Droid", aptoide: "Aptoide" };

type Release = { version_name: string; version_code: number; added_at: string | null; variant?: "web" } & ({ sha256: string } | { id: string });
type StoreApplication = { package_name: string; name: string; versions: Release[] };

export function ApkStorePicker({ busy, importing, canSelectPackage, onImport }: {
  busy: boolean;
  importing: boolean;
  canSelectPackage: (packageName: string) => boolean;
  onImport: (store: ApkStore, packageName: string, releaseId: string) => void;
}) {
  const { t, locale } = useLocale();
  const [store, setStore] = useState<ApkStore>("fdroid");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<StoreApplication[] | null>(null);
  const [packageName, setPackageName] = useState("");
  const [releaseId, setReleaseId] = useState("");
  const [lookup, setLookup] = useState<{ app: StoreApplication; versions: Release[] | null } | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");
  const sequence = useRef(0);
  const application = results?.find(item => item.package_name === packageName);
  const versions = store === "fdroid" ? application?.versions : lookup?.app === application ? lookup?.versions : undefined;
  const date = new Intl.DateTimeFormat(localeInfo[locale].intl, { dateStyle: "medium", timeZone: "UTC" });
  const options = versions?.map(item => {
    const added = item.added_at ? new Date(item.added_at) : null;
    const version = `${item.version_name} (${item.version_code})`;
    const addedDate = added && Number.isFinite(added.getTime()) ? date.format(added) : "";
    return {
      id: "sha256" in item ? item.sha256 : item.id,
      label: [version, addedDate, item.variant === "web" ? "Web" : ""].filter(Boolean).join(" · ")
    };
  }) ?? [];
  const labels = new Map<string, number>();
  for (const { label } of options) labels.set(label, (labels.get(label) ?? 0) + 1);
  const release = options.find(item => item.id === releaseId) ?? options[0];
  const canSearch = query.trim().length >= 2 && !busy && !searching;

  useEffect(() => {
    if (store !== "aptoide" || !application) return;
    let active = true;
    void api<{ versions: Release[] }>(`console/applications/aptoide/versions?${new URLSearchParams({ q: application.package_name })}`)
      .then(response => { if (active) setLookup({ app: application, versions: response.versions }); })
      .catch(() => { if (active) setLookup({ app: application, versions: null }); });
    return () => { active = false; };
  }, [store, application]);

  function resetSearch() {
    sequence.current++;
    setResults(null);
    setLookup(null);
    setError("");
    setSearching(false);
  }

  async function search() {
    if (!canSearch) return;
    const request = ++sequence.current;
    setSearching(true);
    setError("");
    setResults(null);
    setLookup(null);
    try {
      const { items } = await api<{ items: StoreApplication[] }>(`console/applications/${store}?${new URLSearchParams({ q: query.trim() })}`);
      if (sequence.current !== request) return;
      setResults(items);
      setPackageName(items[0]?.package_name ?? "");
      setReleaseId("");
    } catch (failure) {
      if (sequence.current !== request) return;
      setError(failure instanceof ApiError && [401, 403].includes(failure.status)
        ? failure.message : t("Le catalogue {store} est indisponible. Réessayez.", { store: apkStoreNames[store] }));
    } finally {
      if (sequence.current === request) setSearching(false);
    }
  }

  return <div className="emulator-store">
    <label className="emulator-store-source">{t("Source des APK")}
      <select value={store} disabled={busy} onChange={event => {
        setStore(event.target.value === "aptoide" ? "aptoide" : "fdroid");
        resetSearch();
      }}>
        <option value="fdroid">F-Droid</option>
        <option value="aptoide">Aptoide</option>
      </select>
    </label>
    <label className="emulator-store-query">
      {t("Rechercher une application")}
      <input type="search" value={query} maxLength={100} disabled={busy}
        placeholder={t("Nom ou identifiant de l’application")}
        onChange={event => { setQuery(event.target.value); resetSearch(); }}
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
    {searching && <p className="small-copy" role="status">{t("Recherche sur {store}…", { store: apkStoreNames[store] })}</p>}
    {error && <ErrorNotice message={error} />}
    {results?.length === 0 && <p className="small-copy" role="status">{t("Aucun APK trouvé. Essayez un autre nom ou identifiant.")}</p>}
    {application && <div className="emulator-store-results">
      <label>{t("Application")}
        <select value={packageName} disabled={busy} onChange={event => {
          setPackageName(event.target.value);
          setReleaseId("");
          setLookup(null);
        }}>
          {results?.map(item => <option key={item.package_name} value={item.package_name}>{item.name} · {item.package_name}</option>)}
        </select>
      </label>
      {versions === undefined && <p className="small-copy" role="status">{t("Chargement…")}</p>}
      {versions === null && <ErrorNotice message={t("Les versions n’ont pas pu être chargées. Relancez la recherche.")} />}
      {versions?.length === 0 && <p className="small-copy" role="status">{t("Aucun APK compatible avec Android 10 x86_64 pour cette application.")}</p>}
      {release && <>
        <label>{t("Version et date d’ajout")}
          <select value={release.id} disabled={busy} onChange={event => setReleaseId(event.target.value)}>
            {options.map(item => <option key={item.id} value={item.id}>
              {labels.get(item.label) === 1 ? item.label : `${item.label} · ${item.id.slice(-8)}`}
            </option>)}
          </select>
        </label>
        <button type="button" className="button button--secondary" disabled={busy || !canSelectPackage(packageName)}
          onClick={() => onImport(store, packageName, release.id)}>
          <Icon name="plus" size={16} />{importing ? t("Importation en cours…") : t("Importer depuis {store}", { store: apkStoreNames[store] })}
        </button>
      </>}
    </div>}
  </div>;
}
