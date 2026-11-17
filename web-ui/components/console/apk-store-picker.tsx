"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "../../lib/client-api";
import { useLocale } from "../../lib/i18n";
import { localeInfo } from "../../lib/i18n-core";
import { Icon } from "./icons";
import { ErrorNotice } from "./shared";

export type ApkStore = "fdroid" | "aptoide";
type CatalogStore = ApkStore | "apkmirror";
export const apkStoreNames = { fdroid: "F-Droid", aptoide: "Aptoide", apkmirror: "APKMirror" };
const catalogs: CatalogStore[] = ["fdroid", "aptoide", "apkmirror"];

type Release = { version_name: string; version_code?: number | null; added_at: string | null; variant?: "web"; source_url?: string } &
  ({ sha256: string } | { id: string });
type StoreApplication = { package_name?: string; id?: string; name: string; versions: Release[]; source_url?: string };
type SearchReply = { items: StoreApplication[] };

function mirrorLink(value?: string): string | undefined {
  if (!value) return;
  try {
    const url = new URL(value);
    if (url.origin === "https://www.apkmirror.com" && !url.username && !url.password) return url.href;
  } catch {
    return;
  }
}

export function ApkStorePicker({ busy, importing, canSelectPackage, onImport }: {
  busy: boolean;
  importing: boolean;
  canSelectPackage: (packageName: string) => boolean;
  onImport: (store: ApkStore, packageName: string, releaseId: string) => void;
}) {
  const { t, locale } = useLocale();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Partial<Record<CatalogStore, SearchReply | null>> | null>(null);
  const [selected, setSelected] = useState("");
  const [releaseId, setReleaseId] = useState("");
  const [lookup, setLookup] = useState<{ app: StoreApplication; versions: Release[] | null } | null>(null);
  const [searching, setSearching] = useState(false);
  const sequence = useRef(0);
  const matches = catalogs.flatMap(store => (results?.[store]?.items ?? []).flatMap(app => {
    const id = store === "apkmirror" ? app.id : app.package_name;
    return id ? [{ key: `${store}:${id}`, id, app, store }] : [];
  }));
  const selection = matches.find(match => match.key === selected) ?? matches[0];
  const store = selection?.store;
  const application = selection?.app;
  const appId = selection?.id;
  const versions = store === "fdroid" ? application?.versions : lookup?.app === application ? lookup?.versions : undefined;
  const date = new Intl.DateTimeFormat(localeInfo[locale].intl, { dateStyle: "medium", timeZone: "UTC" });
  const options = versions?.map(item => {
    const added = item.added_at ? new Date(item.added_at) : null;
    const version = item.version_code == null ? item.version_name : `${item.version_name} (${item.version_code})`;
    const addedDate = added && Number.isFinite(added.getTime()) ? date.format(added) : "";
    return {
      id: "sha256" in item ? item.sha256 : item.id,
      label: [version, addedDate, item.variant === "web" ? "Web" : ""].filter(Boolean).join(" · "),
      sourceUrl: item.source_url
    };
  }) ?? [];
  const labels = new Map<string, number>();
  for (const { label } of options) labels.set(label, (labels.get(label) ?? 0) + 1);
  const release = options.find(item => item.id === releaseId) ?? options[0];
  const browserUrl = store === "apkmirror" ? mirrorLink(release?.sourceUrl) ?? mirrorLink(application?.source_url) : undefined;
  const mirrorResult = results?.apkmirror;
  const mirrorSearchUrl = mirrorResult === null || mirrorResult?.items.length === 0
    ? `https://www.apkmirror.com/?${new URLSearchParams({ post_type: "app_release", searchtype: "app", s: query.trim() })}`
    : undefined;
  const canSearch = query.trim().length >= 2 && !busy && !searching;

  useEffect(() => {
    if ((store !== "aptoide" && store !== "apkmirror") || !application || !appId) return;
    let active = true;
    void api<{ versions: Release[] }>(`console/applications/${store}/versions?${new URLSearchParams({ q: appId })}`)
      .then(response => { if (active) setLookup({ app: application, versions: response.versions }); })
      .catch(() => { if (active) setLookup({ app: application, versions: null }); });
    return () => { active = false; };
  }, [store, application, appId]);

  function resetSearch() {
    sequence.current++;
    setResults(null);
    setSelected("");
    setReleaseId("");
    setLookup(null);
    setSearching(false);
  }

  async function search() {
    if (!canSearch) return;
    resetSearch();
    const request = sequence.current;
    setSearching(true);
    const params = new URLSearchParams({ q: query.trim() });
    await Promise.all(catalogs.map(async source => {
      let reply: SearchReply | null;
      try {
        reply = await api<SearchReply>(`console/applications/${source}?${params}`);
        if (!Array.isArray(reply?.items)) reply = null;
      } catch {
        reply = null;
      }
      if (sequence.current !== request) return;
      setResults(previous => ({ ...previous, [source]: reply }));
      const first = reply?.items[0];
      const id = source === "apkmirror" ? first?.id : first?.package_name;
      if (id) setSelected(previous => previous || `${source}:${id}`);
    }));
    if (sequence.current === request) setSearching(false);
  }

  return <div className="emulator-store">
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
    <p className="small-copy">{catalogs.map(source => apkStoreNames[source]).join(" · ")}</p>
    {searching && <p className="small-copy" role="status">{t("Recherche dans les catalogues…")}</p>}
    {catalogs.filter(source => results?.[source] === null).map(source => <p key={source} className="small-copy" role="status">
      {t("Catalogue {store} indisponible. Vous pouvez relancer la recherche.", { store: apkStoreNames[source] })}
    </p>)}
    {!searching && results && Object.values(results).some(Boolean) && matches.length === 0 &&
      <p className="small-copy" role="status">{t("Aucun APK trouvé. Essayez un autre nom ou identifiant.")}</p>}
    {selection && <div className="emulator-store-results">
      <label>{t("Application")}
        <select value={selection.key} disabled={busy} onChange={event => {
          if (event.target.value === selection.key) return;
          setSelected(event.target.value);
          setReleaseId("");
          setLookup(null);
        }}>
          {catalogs.map(source => {
            const group = matches.filter(match => match.store === source);
            return group.length > 0 && <optgroup key={source} label={apkStoreNames[source]}>
              {group.map(({ app, key }) => <option key={key} value={key}>
                {[app.name, app.package_name, apkStoreNames[source]].filter(Boolean).join(" · ")}
              </option>)}
            </optgroup>;
          })}
        </select>
      </label>
      {versions === undefined && <p className="small-copy" role="status">{t("Chargement…")}</p>}
      {versions === null && <ErrorNotice message={t("Les versions n’ont pas pu être chargées. Relancez la recherche.")} />}
      {versions?.length === 0 && store !== "apkmirror" && <p className="small-copy" role="status">{t("Aucun APK compatible avec Android 10 x86_64 pour cette application.")}</p>}
      {release && <label>{t("Version et date d’ajout")}
        <select value={release.id} disabled={busy} onChange={event => setReleaseId(event.target.value)}>
          {options.map(item => <option key={item.id} value={item.id}>
            {labels.get(item.label) === 1 ? item.label : `${item.label} · ${item.id.slice(-8)}`}
          </option>)}
        </select>
      </label>}
      {release && (store === "fdroid" || store === "aptoide") && appId && <button type="button" className="button button--secondary"
        disabled={busy || !canSelectPackage(appId)} onClick={() => onImport(store, appId, release.id)}>
        <Icon name="plus" size={16} />{importing ? t("Importation en cours…") : t("Importer depuis {store}", { store: apkStoreNames[store] })}
      </button>}
      {browserUrl && <>
        <a className="button button--secondary" href={browserUrl} target="_blank" rel="noopener noreferrer">{t("Ouvrir sur APKMirror")}<Icon name="arrow" size={15} /></a>
        <p className="small-copy">{t("Téléchargez un APK compatible, puis importez le fichier ci-dessous.")}</p>
      </>}
    </div>}
    {mirrorSearchUrl && <a className="text-button emulator-store-external" href={mirrorSearchUrl} target="_blank" rel="noopener noreferrer">
      {t("Ouvrir sur APKMirror")}<Icon name="arrow" size={15} />
    </a>}
  </div>;
}
