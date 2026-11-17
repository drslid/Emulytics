"use client";

import { useRef, useState, type FormEvent } from "react";
import { api, ApiError } from "../../lib/client-api";
import type { Device } from "../../lib/console-types";
import { useT } from "../../lib/i18n";
import { Dialog, ErrorNotice } from "./shared";

type DeviceInventoryTarget = Pick<Device, "device_id" | "display_name" | "availability" | "emulator_state">;
export type DeviceInventoryAction = { mode: "rename" | "remove"; device: DeviceInventoryTarget };
export const managedEmulatorAnchor = (id: string) => `managed-emulator-${id}`;

const removalErrors = {
  device_busy: "Attendez la fin des opérations sur cet appareil et résolvez les éventuelles vérifications en attente.",
  stop_emulator_first: "Éteignez l’émulateur avant de le supprimer de l’inventaire.",
  device_scheduled: "Désactivez ou modifiez les planifications qui ciblent cet appareil avant de le supprimer."
};

export function DeviceInventoryActions({ device, onAction }: { device: DeviceInventoryTarget; onAction: (action: DeviceInventoryAction) => void }) {
  const t = useT();
  const name = device.display_name || device.device_id;
  return <>
    <button type="button" className="text-button" aria-label={t("Modifier le nom de {name}", { name })}
      onClick={() => onAction({ mode: "rename", device })}>{t("Modifier")}</button>
    <button type="button" className="text-button device-remove" aria-label={t("Supprimer {name} de l’inventaire", { name })}
      onClick={() => onAction({ mode: "remove", device })}>{t("Supprimer")}</button>
  </>;
}

export function DeviceInventoryDialog({ action, onClose, onSaved, onRemoved }: {
  action: DeviceInventoryAction;
  onClose: () => void;
  onSaved: (device: Device) => void;
  onRemoved: (id: string) => void;
}) {
  const t = useT();
  const { device, mode } = action;
  const renaming = mode === "rename";
  const managed = device.emulator_state != null;
  const [name, setName] = useState(device.display_name);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const sending = useRef(false);
  const cleanName = name.trim();
  const blocked = renaming ? "" : device.availability !== "declared" ? removalErrors.device_busy
    : managed && device.emulator_state !== "created" && device.emulator_state !== "stopped" ? removalErrors.stop_emulator_first : "";
  const disabled = busy || !!blocked || renaming && (!cleanName || cleanName === device.display_name);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (disabled || sending.current) return;
    sending.current = true;
    setBusy(true);
    setError("");
    const path = `console/devices/${encodeURIComponent(device.device_id)}`;
    try {
      if (renaming) onSaved(await api<Device>(path, { display_name: cleanName }, "PATCH"));
      else {
        await api<null>(path, undefined, "DELETE");
        onRemoved(device.device_id);
      }
    } catch (failure) {
      const code = failure instanceof ApiError ? failure.code : undefined;
      setError(code && Object.hasOwn(removalErrors, code) ? t(removalErrors[code as keyof typeof removalErrors])
        : failure instanceof ApiError ? failure.message : t("Le service est indisponible. Réessayez dans un instant."));
    } finally {
      sending.current = false;
      setBusy(false);
    }
  }

  return <Dialog title={t(renaming ? "Modifier le nom de l’appareil" : "Supprimer de l’inventaire ?")}
    description={renaming ? undefined : t(managed
      ? "Les exécutions passées et le stockage Android de cet émulateur seront conservés."
      : "Les exécutions passées sont conservées. Vous pourrez reconnecter cet appareil.")}
    onClose={() => { if (!sending.current) onClose(); }}>
    <form className="dialog-form" onSubmit={submit} aria-busy={busy}>
      {renaming ? <label>{t("Nom affiché")}
        <input required autoFocus maxLength={160} value={name} disabled={busy} onChange={event => setName(event.target.value)} />
      </label> : <p className="device-removal-target"><bdi>{device.display_name || device.device_id}</bdi></p>}
      {blocked && <p className="notice notice--warning">{t(blocked)}</p>}
      {error && <ErrorNotice message={error} />}
      <div className="dialog-footer">
        <button type="button" className="button button--secondary" autoFocus={!renaming} disabled={busy} onClick={onClose}>{t("Annuler")}</button>
        <button type="submit" className={`button ${renaming ? "button--primary" : "button--danger"}`} disabled={disabled}>
          {t(busy ? "Demande en cours…" : renaming ? "Enregistrer" : "Supprimer de l’inventaire")}
        </button>
      </div>
    </form>
  </Dialog>;
}
