"use client";
import { useState, type FormEvent } from "react";
import { api } from "../../lib/client-api";
import { useT } from "../../lib/i18n";
import { Dialog, ErrorNotice } from "./shared";

export function DeviceForm({
  onClose,
  onAdded,
  hosts = [],
}: {
  onClose: () => void;
  onAdded: () => void;
  hosts?: string[];
}) {
  const t = useT();
  const [suffix] = useState(() => crypto.getRandomValues(new Uint32Array(1))[0].toString(16).padStart(8, "0"));
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const name = String(values.get("name") ?? "").trim();
    const normalized = name
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9_.:-]+/g, "-")
      .replace(/^[^a-z0-9]+|[^a-z0-9]+$/g, "")
      .slice(0, 100);
    setBusy(true);
    setError("");
    try {
      await api("devices", {
        device_id: `${normalized || "device"}-${suffix}`,
        display_name: name,
        host_id: String(values.get("host_id")).trim().replace(/\s+/g, "-"),
        serial: String(values.get("serial")).trim(),
        kind: values.get("kind"),
      });
      onAdded();
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title={t("Ajouter un appareil")}
      description={t(
        "Connectez un téléphone Android ou un émulateur à votre flotte.",
      )}
      onClose={onClose}
    >
      <form onSubmit={submit} className="dialog-form">
        <div className="notice notice--info">
          {t(
            "L’appareil est enregistré ici. Le worker doit être connecté à Android pour exécuter vos parcours.",
          )}
        </div>
        {error && <ErrorNotice message={error} />}
        <label>
          {t("Nom de l’appareil")}
          <input
            name="name"
            required
            maxLength={160}
            placeholder={t("Ex. Téléphone de Paris")}
            autoFocus
          />
          <span>
            {t(
              "Les espaces sont acceptés. L’identifiant est généré automatiquement.",
            )}
          </span>
        </label>
        <label>
          {t("Type d’appareil")}
          <select name="kind">
            <option value="physical">{t("Téléphone Android physique")}</option>
            <option value="emulator">{t("Émulateur Android")}</option>
          </select>
        </label>
        <label>
          {t("Worker de connexion")}
          <input
            name="host_id"
            list="worker-hosts"
            required
            maxLength={128}
            defaultValue={hosts.length === 1 ? hosts[0] : ""}
            placeholder="bench-host"
          />
          <datalist id="worker-hosts">
            {hosts.map((h) => (
              <option key={h} value={h} />
            ))}
          </datalist>
          <span>
            {t("Choisissez le worker auquel l’appareil est connecté.")}
            {" "}{t("Les hôtes proposés correspondent aux workers actuellement actifs.")}
          </span>
        </label>
        <label>
          {t("Identifiant Android (ADB)")}
          <input
            name="serial"
            required
            maxLength={128}
            placeholder="emulator-5554"
            dir="ltr"
          />
          <span>
            {t(
              "Copiez le numéro affiché par adb devices. Les espaces autour sont retirés.",
            )}
          </span>
        </label>
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
            {t(busy ? "Ajout en cours…" : "Ajouter l’appareil")}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
