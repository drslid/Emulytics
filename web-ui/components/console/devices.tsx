"use client";

import { useLocale } from "../../lib/i18n";

import { useState } from "react";
import type { Device } from "../../lib/console-types";
import { Badge, Empty } from "./shared";
import { Icon } from "./icons";
import { DeviceConnection } from "./device-connection";
import { canSubmitDevices, isDeviceReady } from "../../lib/device-readiness";

export function Devices({ devices, total, offset, onPage, selected, onSelect, onAdd, onLaunch, canAdd = true, canLaunch = true }: {
  devices: Device[]; total: number; offset: number; onPage: (offset: number) => void;
  selected: string[]; onSelect: (ids: string[]) => void; onAdd: () => void; onLaunch: () => void; canAdd?: boolean; canLaunch?: boolean;
}) {
  const { t, locale } = useLocale();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [kind, setKind] = useState("all");
  const visible = devices.filter((device) => `${device.display_name ?? ""} ${device.device_id} ${device.host_id} ${device.serial}`.toLocaleLowerCase(locale).includes(search.toLocaleLowerCase(locale)) && (status === "all" || device.availability === status) && (kind === "all" || device.kind === kind));
  const selectable = visible.filter(isDeviceReady);
  const allSelected = selectable.length > 0 && selectable.every((device) => selected.includes(device.device_id));
  const toggle = (id: string) => onSelect(selected.includes(id) ? selected.filter((value) => value !== id) : [...selected, id].slice(0, 100));
  return <>
    <div className="section-heading"><div><h2>{t("Votre flotte")} <span className="count-label">{total}</span></h2><p>{t("Un inventaire central, quel que soit l’hôte de connexion.")}</p></div>{canAdd && <button className="button button--secondary" onClick={onAdd}><Icon name="plus" />{t("Ajouter un téléphone")}</button>}</div>
    <section className="surface">
      <div className="table-toolbar"><label className="search-field"><Icon name="search" /><input type="search" aria-label={t("Rechercher un téléphone dans la page")} placeholder={t("Rechercher un téléphone…")} value={search} onChange={(event) => setSearch(event.target.value)} /></label><label className="filter-field"><span>{t("État")}</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">{t("Tous les états")}</option><option value="declared">{t("Déclarés")}</option><option value="busy">{t("Occupés")}</option><option value="needs_review">{t("À vérifier")}</option></select></label><label className="filter-field"><span>{t("Type")}</span><select value={kind} onChange={(event) => setKind(event.target.value)}><option value="all">{t("Tous les types")}</option><option value="physical">{t("Physiques")}</option><option value="emulator">{t("Émulateurs")}</option></select></label></div>
      {selected.length > 0 && <div className="selection-bar" role="status"><strong>{t("{count} appareil(s) sélectionné(s)", {count: selected.length})}</strong><div><button className="text-button" onClick={() => onSelect([])}>{t("Désélectionner")}</button>{canLaunch && <button className="button button--primary button--small" disabled={!canSubmitDevices(selected, devices)} onClick={onLaunch}><Icon name="play" size={16} />{t("Lancer sur la sélection")}</button>}</div></div>}
      {!devices.length ? <Empty title={t("Ajoutez votre premier téléphone")} action={canAdd ? <button className="button button--primary" onClick={onAdd}><Icon name="plus" />{t("Ajouter un téléphone")}</button> : undefined}>{t("Déclarez un appareil physique ou un émulateur pour lui attribuer une automatisation.")}</Empty> : !visible.length ? <Empty icon="search" title={t("Aucun téléphone ne correspond")}>{t("Modifiez la recherche ou les filtres de cette page.")}</Empty> : <div className="table-scroll" tabIndex={0} role="region" aria-label={t("Liste des téléphones")}><table className="data-table"><caption className="sr-only">{t("Téléphones déclarés et disponibilité du worker")}</caption><thead><tr><th className="checkbox-cell"><input type="checkbox" aria-label={t("Sélectionner les téléphones disponibles de cette page")} checked={allSelected} onChange={() => onSelect(allSelected ? selected.filter((id) => !selectable.some((device) => device.device_id === id)) : [...new Set([...selected, ...selectable.map((device) => device.device_id)])].slice(0, 100))} /></th><th>{t("Téléphone")}</th><th>{t("État")}</th><th>{t("Connexion")}</th><th>{t("Hôte")}</th><th>{t("Identifiant Android")}</th><th>{t("Type")}</th></tr></thead><tbody>{visible.map((device) => <tr key={device.device_id} className={selected.includes(device.device_id) ? "row-selected" : ""}><td className="checkbox-cell"><input type="checkbox" aria-label={t("Sélectionner {name}", { name: device.display_name || device.device_id })} checked={selected.includes(device.device_id)} disabled={!isDeviceReady(device) || (!selected.includes(device.device_id) && selected.length >= 100)} onChange={() => toggle(device.device_id)} /></td><th scope="row"><div className="device-name"><span className="device-symbol"><Icon name="phone" size={20} /></span><span>{device.display_name || device.device_id}</span></div></th><td><Badge status={device.availability} /></td><td><DeviceConnection device={device} /></td><td>{device.host_id}</td><td><code>{device.serial}</code></td><td>{device.kind === "emulator" ? t("Émulateur") : t("Physique")}</td></tr>)}</tbody></table></div>}
      <div className="table-footer"><span>{total ? t("{start}–{end} sur {total}", { start: offset + 1, end: Math.min(offset + devices.length, total), total }) : t("0 téléphone")}{total > 100 ? t(" · filtres sur cette page") : ""}</span><div className="pagination"><button className="text-button" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - 100))}>{t("Précédent")}</button><button className="text-button" disabled={offset + devices.length >= total} onClick={() => onPage(offset + 100)}>{t("Suivant")}</button></div></div>
    </section>
    <p className="context-note"><Icon name="shield" size={16} />{t("Un lancement immédiat nécessite un worker actif et une connexion Android vérifiée. Les appareils indisponibles restent visibles pour être corrigés.")}</p>
  </>;
}
