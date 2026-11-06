"use client";

import { useState, type FormEvent } from "react";
import { api } from "../../lib/client-api";
import { Dialog, ErrorNotice } from "./shared";

export function DeviceForm({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    setBusy(true); setError("");
    try {
      await api("devices", { device_id: values.get("device_id"), host_id: values.get("host_id"), serial: values.get("serial"), kind: values.get("kind") });
      onAdded();
    } catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }
  return <Dialog title="Ajouter un téléphone" description="Déclarez l’appareil auprès de son worker." onClose={onClose}>
    <form onSubmit={submit} className="dialog-form">
      <div className="notice notice--info">L’ajout déclare l’appareil. Sa connexion Android doit être configurée sur l’hôte du worker.</div>
      {error && <ErrorNotice message={error} />}
      <label>Nom de l’appareil<input name="device_id" required maxLength={128} pattern="[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}" placeholder="pixel-bureau" autoFocus /><span>Identifiant unique, sans espaces.</span></label>
      <label>Type<select name="kind"><option value="physical">Téléphone physique</option><option value="emulator">Émulateur Android</option></select></label>
      <label>Hôte du worker<input name="host_id" required maxLength={128} pattern="[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}" placeholder="bench-host" /><span>Le nom d’hôte configuré pour le worker.</span></label>
      <label>Identifiant Android (ADB)<input name="serial" required maxLength={128} pattern="[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}" placeholder="emulator-5554" /><span>Le numéro affiché par ADB sur cet hôte.</span></label>
      <div className="dialog-footer"><button type="button" className="button button--secondary" disabled={busy} onClick={onClose}>Annuler</button><button className="button button--primary" disabled={busy}>{busy ? "Ajout en cours…" : "Ajouter le téléphone"}</button></div>
    </form>
  </Dialog>;
}
