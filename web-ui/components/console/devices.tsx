"use client";

import { useState } from "react";
import type { Device } from "../../lib/console-types";
import { Badge, Empty } from "./shared";
import { Icon } from "./icons";

export function Devices({ devices, total, offset, onPage, selected, onSelect, onAdd, onLaunch }: {
  devices: Device[]; total: number; offset: number; onPage: (offset: number) => void;
  selected: string[]; onSelect: (ids: string[]) => void; onAdd: () => void; onLaunch: () => void;
}) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [kind, setKind] = useState("all");
  const visible = devices.filter((device) => `${device.device_id} ${device.host_id} ${device.serial}`.toLocaleLowerCase("fr").includes(search.toLocaleLowerCase("fr")) && (status === "all" || device.availability === status) && (kind === "all" || device.kind === kind));
  const selectable = visible.filter((device) => device.availability !== "needs_review");
  const allSelected = selectable.length > 0 && selectable.every((device) => selected.includes(device.device_id));
  const toggle = (id: string) => onSelect(selected.includes(id) ? selected.filter((value) => value !== id) : [...selected, id].slice(0, 100));
  return <>
    <div className="section-heading"><div><h2>Votre flotte <span className="count-label">{total}</span></h2><p>Un inventaire central, quel que soit l’hôte de connexion.</p></div><button className="button button--secondary" onClick={onAdd}><Icon name="plus" />Ajouter un téléphone</button></div>
    <section className="surface">
      <div className="table-toolbar"><label className="search-field"><Icon name="search" /><input type="search" aria-label="Rechercher un téléphone dans la page" placeholder="Rechercher un téléphone…" value={search} onChange={(event) => setSearch(event.target.value)} /></label><label className="filter-field"><span>État</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">Tous les états</option><option value="declared">Déclarés</option><option value="busy">Occupés</option><option value="needs_review">À vérifier</option></select></label><label className="filter-field"><span>Type</span><select value={kind} onChange={(event) => setKind(event.target.value)}><option value="all">Tous les types</option><option value="physical">Physiques</option><option value="emulator">Émulateurs</option></select></label></div>
      {selected.length > 0 && <div className="selection-bar" role="status"><strong>{selected.length} téléphone{selected.length > 1 ? "s" : ""} sélectionné{selected.length > 1 ? "s" : ""}</strong><div><button className="text-button" onClick={() => onSelect([])}>Désélectionner</button><button className="button button--primary button--small" onClick={onLaunch}><Icon name="play" size={16} />Lancer sur la sélection</button></div></div>}
      {!devices.length ? <Empty title="Ajoutez votre premier téléphone" action={<button className="button button--primary" onClick={onAdd}><Icon name="plus" />Ajouter un téléphone</button>}>Déclarez un appareil physique ou un émulateur pour lui attribuer une automatisation.</Empty> : !visible.length ? <Empty icon="search" title="Aucun téléphone ne correspond">Modifiez la recherche ou les filtres de cette page.</Empty> : <div className="table-scroll" tabIndex={0} role="region" aria-label="Liste des téléphones"><table className="data-table"><caption className="sr-only">Téléphones déclarés et disponibilité du worker</caption><thead><tr><th className="checkbox-cell"><input type="checkbox" aria-label="Sélectionner les téléphones disponibles de cette page" checked={allSelected} onChange={() => onSelect(allSelected ? selected.filter((id) => !selectable.some((device) => device.device_id === id)) : [...new Set([...selected, ...selectable.map((device) => device.device_id)])].slice(0, 100))} /></th><th>Téléphone</th><th>État</th><th>Hôte</th><th>Identifiant Android</th><th>Type</th></tr></thead><tbody>{visible.map((device) => <tr key={device.device_id} className={selected.includes(device.device_id) ? "row-selected" : ""}><td className="checkbox-cell"><input type="checkbox" aria-label={`Sélectionner ${device.device_id}`} checked={selected.includes(device.device_id)} disabled={device.availability === "needs_review" || (!selected.includes(device.device_id) && selected.length >= 100)} onChange={() => toggle(device.device_id)} /></td><th scope="row"><div className="device-name"><span className="device-symbol"><Icon name="phone" size={20} /></span><span>{device.device_id}</span></div></th><td><Badge status={device.availability} /></td><td>{device.host_id}</td><td><code>{device.serial}</code></td><td>{device.kind === "emulator" ? "Émulateur" : "Physique"}</td></tr>)}</tbody></table></div>}
      <div className="table-footer"><span>{total ? `${offset + 1}–${Math.min(offset + devices.length, total)} sur ${total}` : "0 téléphone"}{total > 100 ? " · filtres sur cette page" : ""}</span><div className="pagination"><button className="text-button" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - 100))}>Précédent</button><button className="text-button" disabled={offset + devices.length >= total} onClick={() => onPage(offset + 100)}>Suivant</button></div></div>
    </section>
    <p className="context-note"><Icon name="shield" size={16} />« Déclaré » indique une inscription, pas une connexion Android vérifiée. Un appareil « À vérifier » reste bloqué jusqu’à sa revue.</p>
  </>;
}
