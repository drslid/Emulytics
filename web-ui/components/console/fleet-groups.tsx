"use client";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError } from "../../lib/client-api";
import type { Device } from "../../lib/console-types";
import { canSubmitDevices } from "../../lib/device-readiness";
import { bulkIntentKey, managedBulkTargets, parseBulkIntent, type BulkAction, type BulkIntent, type BulkResult, type FleetCapacity, type FleetGroup, type FleetGroupDetail } from "../../lib/fleet-groups";
import { fleetCopy } from "../../lib/fleet-groups-copy";
import { useLocale } from "../../lib/i18n";
import { Badge, Dialog, ErrorNotice } from "./shared";
import { DeviceConnection } from "./device-connection";
import { Icon } from "./icons";

const actionLabels = {start:"Allumer",prepare:"Préparer les applications",stop:"Éteindre"};
// A 409 can mean the same bulk request is still running; keep its immutable replay key.
const definite = (error: unknown) => error instanceof ApiError && [401,403,404,422].includes(error.status);

export function FleetGroups({userId,devices,canManage,canLaunch,onLaunch,onChanged,onOpenRun}: {
 userId:string; devices:Device[]; canManage:boolean; canLaunch:boolean; onLaunch:(ids:string[],devices:Device[])=>void; onChanged:()=>void; onOpenRun:(id:string)=>void;
}) {
 const {t,locale}=useLocale(), copy=fleetCopy[locale];
 const [groups,setGroups]=useState<FleetGroup[]>([]),[capacity,setCapacity]=useState<FleetCapacity|null>(null),[selected,setSelected]=useState("");
 const [detail,setDetail]=useState<FleetGroupDetail|null>(null),[loading,setLoading]=useState(false),[error,setError]=useState(""),[capacityError,setCapacityError]=useState(false);
 const [editing,setEditing]=useState<FleetGroup|null|undefined>(undefined),[deleting,setDeleting]=useState(false),[busy,setBusy]=useState(false);
 const [review,setReview]=useState<BulkIntent|null>(null),[pending,setPending]=useState<BulkIntent|null>(null),[result,setResult]=useState<BulkResult|null>(null);
 const mounted=useRef(false),seq=useRef(0),sending=useRef(false),capacityLoading=useRef(false),chosen=useRef(selected);
 chosen.current=selected;
 const loadCapacity=useCallback(async()=>{
   if(capacityLoading.current || document.visibilityState==="hidden")return;
   capacityLoading.current=true;
   try { const response=await api<FleetCapacity>("console/fleet/capacity"); if(mounted.current){setCapacity(response);setCapacityError(false);} }
   catch {if(mounted.current){setCapacity(null);setCapacityError(true);}}
   finally {capacityLoading.current=false;}
 },[]);
 const loadGroups=useCallback(async()=>{
   try {const response=await api<{items:FleetGroup[]}>("console/fleet/groups"); if(mounted.current){setGroups(response.items);setSelected(current=>response.items.some(group=>group.id===current)?current:"");setError("");}}
   catch(failure){if(mounted.current)setError((failure as Error).message);}
 },[]);
 useEffect(()=>{
   mounted.current=true;void loadGroups();void loadCapacity();
   if(canManage)try {const saved=sessionStorage.getItem(bulkIntentKey(userId));if(saved)setPending(parseBulkIntent(JSON.parse(saved)));}catch{/* Sending still requires durable session storage. */}
   const visible=()=>{if(document.visibilityState!=="hidden")void loadCapacity();};
   const timer=setInterval(()=>void loadCapacity(),5000);document.addEventListener("visibilitychange",visible);
   return()=>{mounted.current=false;seq.current++;clearInterval(timer);document.removeEventListener("visibilitychange",visible);};
 },[userId,canManage,loadCapacity,loadGroups]);
 useEffect(()=>{
   const request=++seq.current;setDetail(null);
   if(!selected){setLoading(false);return;}
   setLoading(true);
   let fetching=false;
   const refresh=async()=>{
     if(fetching || document.visibilityState==="hidden")return;fetching=true;
     try{const response=await api<FleetGroupDetail>(`console/fleet/groups/${selected}`);if(mounted.current&&seq.current===request){setDetail(response);setError("");}}
     catch(failure){if(mounted.current&&seq.current===request)setError((failure as Error).message);}
     finally{fetching=false;if(mounted.current&&seq.current===request)setLoading(false);}
   };
   void refresh();const timer=setInterval(()=>void refresh(),5000);
   const visible=()=>{if(document.visibilityState!=="hidden")void refresh();};document.addEventListener("visibilitychange",visible);
   return()=>{clearInterval(timer);document.removeEventListener("visibilitychange",visible);};
 },[selected]);
 async function refreshDetail(){
   if(!selected)return;const id=selected;setLoading(true);setError("");
   try{const response=await api<FleetGroupDetail>(`console/fleet/groups/${id}`);if(mounted.current && chosen.current===id)setDetail(response);}
   catch(failure){if(mounted.current)setError((failure as Error).message);}
   finally{if(mounted.current)setLoading(false);}
 }
 async function launch(){
   if(!selected || !canLaunch || busy)return;const id=selected;setBusy(true);setError("");
   try{const fresh=await api<FleetGroupDetail>(`console/fleet/groups/${id}`);if(chosen.current!==id)return;setDetail(fresh);onLaunch(fresh.group.device_ids,fresh.devices);}
   catch(failure){setError((failure as Error).message);}finally{setBusy(false);}
 }
 async function prepareBulk(action:BulkAction){
   if(!detail || !canManage || pending || busy)return;const ids=[...detail.group.device_ids];setBusy(true);setError("");
   try{const catalog=await api<{items:{device_id:string}[]}>("console/emulators");const targets=managedBulkTargets(ids,catalog.items.map(item=>item.device_id));if(!targets.length){setError(copy.noManaged);return;}setReview({request_id:crypto.randomUUID(),action,device_ids:targets});}
   catch(failure){setError((failure as Error).message);}finally{setBusy(false);}
 }
 async function sendBulk(){
   if(!review || sending.current || !canManage)return;const intent=pending??review;sending.current=true;setBusy(true);setError("");let sent=false;
   try{
     sessionStorage.setItem(bulkIntentKey(userId),JSON.stringify(intent));setPending(intent);sent=true;
     const response=await api<BulkResult>("console/fleet/bulk",intent);setResult(response);try{sessionStorage.removeItem(bulkIntentKey(userId));}catch{}
     setPending(null);setReview(null);onChanged();void loadCapacity();void refreshDetail();
   }catch(failure){
     if(!sent || definite(failure)){try{sessionStorage.removeItem(bulkIntentKey(userId));}catch{}setPending(null);}
     setError(!sent?t("Autorisez le stockage de session du navigateur pour sécuriser cette demande."):(failure as Error).message);
   }finally{sending.current=false;setBusy(false);}
 }
 async function remove(){
   if(!detail || busy || !canManage)return;setBusy(true);setError("");
   try{await api(`console/fleet/groups/${detail.group.id}`,{},"DELETE");setDeleting(false);setSelected("");setDetail(null);await loadGroups();}
   catch(failure){setError((failure as Error).message);}finally{setBusy(false);}
 }
 const members=detail?.devices??[], selectedGroup=detail?.group;
 const known=new Map([...devices,...members].map(device=>[device.device_id,device.display_name||device.device_id]));
 return <section className="fleet-groups" aria-labelledby="fleet-group-heading">
   <div className="section-heading"><div><h2 id="fleet-group-heading">{copy.heading}</h2><p>{copy.description}</p></div><div className="row-actions"><button type="button" className="text-button" onClick={()=>{void loadGroups();void loadCapacity();void refreshDetail();}}><Icon name="refresh" size={16}/>{t("Actualiser")}</button>{canManage&&<button type="button" className="button button--secondary" onClick={()=>setEditing(null)}><Icon name="plus" size={16}/>{copy.create}</button>}</div></div>
   {error&&<ErrorNotice message={error}/>}
   <div className="surface fleet-capacity"><div className="fleet-capacity-grid">{([[copy.available,capacity?.available_slots],[copy.active,capacity?.active_slots],[copy.queued,capacity?.queued_executions],[copy.ready,capacity?.ready_devices]] as const).map(([label,count])=><div key={label}><span>{label}</span><strong>{count===undefined?"—":new Intl.NumberFormat(locale).format(count)}</strong></div>)}</div><p className="small-copy" role={capacityError?"status":undefined}>{capacityError?copy.capacityUnavailable:copy.capacityHint}</p></div>
   <div className="surface fleet-group-panel"><label className="fleet-group-select">{copy.choose}<select value={selected} onChange={event=>setSelected(event.target.value)} disabled={busy}><option value="">{groups.length?copy.choose:copy.empty}</option>{groups.map(group=><option value={group.id} key={group.id}>{group.name} ({group.device_ids.length})</option>)}</select></label>
   {pending&&canManage&&<div className="notice notice--warning"><p>{t("La demande précédente est conservée. Réessayez pour confirmer son résultat.")}</p><button type="button" className="button button--secondary" disabled={busy} onClick={()=>setReview(pending)}>{t("Confirmer le résultat de la demande")}</button></div>}
   {loading&&<p className="small-copy" role="status">{t("En cours")}</p>}
   {selectedGroup&&<><div className="fleet-group-actions"><strong>{t("{count} appareil(s) sélectionné(s)",{count:selectedGroup.device_ids.length})}</strong><div className="row-actions">{canManage&&<><button type="button" className="text-button" disabled={busy} onClick={()=>setEditing(selectedGroup)}>{t("Modifier")}</button><button type="button" className="text-button" disabled={busy} onClick={()=>setDeleting(true)}>{t("Supprimer")}</button></>}{canLaunch&&<button type="button" className="button button--primary" disabled={busy||loading||!canSubmitDevices(selectedGroup.device_ids,members)} onClick={()=>void launch()}><Icon name="play" size={16}/>{t("Lancer un parcours")}</button>}</div></div>
   <ul className="fleet-group-members" aria-label={copy.members}>{members.map(device=><li key={device.device_id}><div><strong>{device.display_name||device.device_id}</strong><small>{device.kind==="physical"?t("Physique"):t("Émulateur")} · <bdi>{device.host_id}</bdi></small></div><DeviceConnection device={device}/><Badge status={device.availability}/></li>)}</ul>
   {canManage&&<><div className="row-actions fleet-bulk-actions">{(["start","prepare","stop"] as const).map(action=><button key={action} type="button" className="button button--secondary" disabled={busy||!!pending||!selectedGroup.device_ids.length} onClick={()=>void prepareBulk(action)}>{t(actionLabels[action])}</button>)}</div><p className="small-copy">{copy.excluded}</p></>}
   </>}
   {result&&<div className="fleet-bulk-results" role="status"><h3>{t(actionLabels[result.action])}</h3><ul>{result.items.map(item=><li key={item.device_id}><strong>{known.get(item.device_id)??item.device_id}</strong><span className={`status-badge status-badge--${item.status==="accepted"?"green":"amber"}`}>{item.status==="accepted"?copy.accepted:copy.rejected}</span>{item.detail&&<small>{item.detail}</small>}{item.run_id&&<button type="button" className="text-button" onClick={()=>onOpenRun(item.run_id!)}>{t("Voir la dernière opération")}</button>}</li>)}</ul></div>}
   </div>
   {editing!==undefined&&<GroupEditor key={editing?.id??"new"} group={editing} initialDevices={members} onClose={()=>setEditing(undefined)} onSaved={group=>{setEditing(undefined);setSelected(group.id);setDetail(null);void loadGroups();void api<FleetGroupDetail>(`console/fleet/groups/${group.id}`).then(response=>{if(mounted.current&&chosen.current===group.id)setDetail(response);}).catch(failure=>{if(mounted.current)setError((failure as Error).message);});onChanged();}}/>}
   {deleting&&detail&&<Dialog title={t("Supprimer")} description={copy.deleteHint} onClose={()=>{if(!busy)setDeleting(false);}}><strong>{detail.group.name}</strong>{error&&<ErrorNotice message={error}/>}<div className="dialog-footer"><button type="button" className="button button--secondary" disabled={busy} onClick={()=>setDeleting(false)}>{t("Annuler")}</button><button type="button" className="button button--primary" disabled={busy} onClick={()=>void remove()}>{t("Supprimer")}</button></div></Dialog>}
   {review&&<Dialog title={t(actionLabels[review.action])} description={copy.confirm} onClose={()=>{if(!busy)setReview(null);}} wide><div className="dialog-form">{error&&<ErrorNotice message={error}/>}<p className="small-copy">{copy.excluded}</p><ul className="fleet-confirm-members">{review.device_ids.map(id=><li key={id}><strong>{known.get(id)??id}</strong><small><bdi>{id}</bdi></small></li>)}</ul>{pending&&<p className="notice notice--warning">{t("La demande précédente est conservée. Réessayez pour confirmer son résultat.")}</p>}<div className="dialog-footer"><button type="button" className="button button--secondary" disabled={busy} onClick={()=>setReview(null)}>{t("Fermer")}</button><button type="button" className="button button--primary" disabled={busy} onClick={()=>void sendBulk()}>{t(busy?"Demande en cours…":pending?"Confirmer le résultat de la demande":actionLabels[review.action])}</button></div></div></Dialog>}
 </section>;
}

function GroupEditor({group,initialDevices,onClose,onSaved}: {group:FleetGroup|null;initialDevices:Device[];onClose:()=>void;onSaved:(group:FleetGroup)=>void}) {
 const {t,locale}=useLocale(),copy=fleetCopy[locale];
 const [name,setName]=useState(group?.name??""),[selected,setSelected]=useState(group?.device_ids??[]),[items,setItems]=useState<Device[]>(initialDevices),[offset,setOffset]=useState(0),[total,setTotal]=useState(0);
 const [search,setSearch]=useState(""),[busy,setBusy]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState("");
 const seq=useRef(0),savedOffset=useRef(0);
 const load=useCallback(async(next:number)=>{const request=++seq.current;setLoading(true);setError("");try{const page=await api<{items:Device[];total:number}>(`console/fleet?limit=100&offset=${next}`);if(seq.current===request){setItems(page.items);setTotal(page.total);setOffset(next);savedOffset.current=next;}}catch(failure){if(seq.current===request)setError((failure as Error).message);}finally{if(seq.current===request)setLoading(false);}},[]);
 useEffect(()=>{void load(0);return()=>{seq.current++;};},[load]);
 async function save(event:FormEvent){event.preventDefault();if(busy || !name.trim() || !selected.length)return;setBusy(true);setError("");try{const payload={name:name.trim(),device_ids:selected,...(group?{revision:group.revision}:{})};onSaved(await api<FleetGroup>(group?`console/fleet/groups/${group.id}`:"console/fleet/groups",payload,group?"PATCH":"POST"));}catch(failure){setError((failure as Error).message);}finally{setBusy(false);}}
 const visible=items.filter(device=>`${device.display_name} ${device.device_id} ${device.host_id}`.toLocaleLowerCase(locale).includes(search.toLocaleLowerCase(locale)));
 return <Dialog title={group?t("Modifier"):copy.create} description={copy.maximum} onClose={()=>{if(!busy)onClose();}} wide><form className="dialog-form" onSubmit={save}>{error&&<ErrorNotice message={error}/>}<label>{t("Nom")}<input required autoFocus maxLength={120} value={name} disabled={busy} onChange={event=>setName(event.target.value)}/></label><fieldset className="fleet-member-picker" disabled={busy}><legend>{copy.members}</legend><input type="search" value={search} aria-label={t("Rechercher un téléphone…")} placeholder={t("Rechercher un téléphone…")} onChange={event=>setSearch(event.target.value)}/><p className="small-copy">{copy.listHint}</p><div className="fleet-member-options">{visible.map(device=><label key={device.device_id}><input type="checkbox" checked={selected.includes(device.device_id)} disabled={!selected.includes(device.device_id)&&selected.length>=100} onChange={()=>setSelected(current=>current.includes(device.device_id)?current.filter(id=>id!==device.device_id):[...current,device.device_id])}/><span><strong>{device.display_name||device.device_id}</strong><small>{device.host_id} · {device.kind==="physical"?t("Physique"):t("Émulateur")}</small></span></label>)}</div><p className="small-copy" role="status">{t("{count} appareil(s) sélectionné(s)",{count:selected.length})}</p><div className="row-actions"><button type="button" className="text-button" disabled={loading||offset===0} onClick={()=>void load(Math.max(0,offset-100))}>{t("Précédent")}</button><button type="button" className="text-button" disabled={loading||offset+items.length>=total} onClick={()=>void load(offset+100)}>{t("Suivant")}</button>{error&&<button type="button" className="text-button" disabled={loading} onClick={()=>void load(savedOffset.current)}>{t("Réessayer")}</button>}</div></fieldset><div className="dialog-footer"><button type="button" className="button button--secondary" disabled={busy} onClick={onClose}>{t("Annuler")}</button><button type="submit" className="button button--primary" disabled={busy||!name.trim()||!selected.length}>{t(busy?"Enregistrement…":"Enregistrer")}</button></div></form></Dialog>;
}
