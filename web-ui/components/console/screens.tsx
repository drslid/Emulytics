"use client";
import { useEffect, useState } from "react";
import type { Device } from "../../lib/console-types";
import { useT } from "../../lib/i18n";
import { DeviceConnection } from "./device-connection";
import { LiveScreen } from "./live-screen";
import { Empty } from "./shared";
import { Icon } from "./icons";

export function Screens({ devices }: { devices: Device[] }) {
  const t = useT();
  const [selectedId, setSelectedId] = useState("");
  const connected = devices.filter(
    (device) => device.connection_status === "connected",
  );
  const firstId = connected[0]?.device_id;
  useEffect(() => {
    if (!selectedId && firstId) setSelectedId(firstId);
  }, [selectedId, firstId]);
  const selected = devices.find((device) => device.device_id === selectedId);
  if (!selected && !connected.length)
    return (
      <section className="surface">
        <Empty
          icon="phone"
          title={t("Aucun appareil connecté")}
          action={
            <a className="button button--secondary" href="/telephones">
              {t("Retour aux appareils")}
            </a>
          }
        >
          {t("Connectez un appareil pour afficher son écran en direct.")}
        </Empty>
      </section>
    );
  return (
    <div className="screens-layout">
      <aside className="surface screens-device-panel">
        <div className="surface-heading">
          <div>
            <h2>{t("Choisir un appareil")}</h2>
            <p>
              {t("Appareils connectés")} · {connected.length}
            </p>
          </div>
        </div>
        <div className="screens-device-list">
          {devices.map((device) => (
            <button
              key={device.device_id}
              className={`screens-device ${selectedId === device.device_id ? "screens-device--selected" : ""}`}
              aria-pressed={selectedId === device.device_id}
              disabled={
                device.connection_status !== "connected" &&
                selectedId !== device.device_id
              }
              onClick={() => setSelectedId(device.device_id)}
            >
              <Icon name="phone" />
              <span>
                <strong>{device.display_name || device.device_id}</strong>
                <small dir="ltr">
                  {device.host_id} · {device.serial}
                </small>
                <DeviceConnection device={device} />
              </span>
            </button>
          ))}
        </div>
        <div className="screens-help">
          <Icon name="shield" size={17} />
          <p>
            {t(
              "L’écran est affiché en direct, indépendamment des captures du parcours.",
            )}
          </p>
        </div>
      </aside>
      <section className="screens-viewer">
        {selected ? (
          <LiveScreen
            key={selected.device_id}
            deviceId={selected.device_id}
            name={selected.display_name || selected.device_id}
          />
        ) : (
          <section className="surface empty-state">
            <Icon name="phone" size={30} />
            <p>{t("Sélectionnez un appareil pour observer son écran.")}</p>
          </section>
        )}
        <p className="screens-cadence">{t("Environ une image par seconde")}</p>
      </section>
    </div>
  );
}
