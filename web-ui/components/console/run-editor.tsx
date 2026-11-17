"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "../../lib/client-api";
import type { Device, RunDetail, Workflow } from "../../lib/console-types";
import { useT } from "../../lib/i18n";
import { RecipeEditor } from "./recipe-editor";
import { ErrorNotice } from "./shared";

type RunSource = { run: RunDetail; workflow: Workflow };

export function RunEditor({ sourceRunId, devices, onPrepared }: {
  sourceRunId?: string;
  devices: Device[];
  onPrepared: (workflow: Workflow, source?: RunDetail) => void;
}) {
  const t = useT();
  const router = useRouter();
  const [source, setSource] = useState<RunSource | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!sourceRunId) return;
    let active = true;
    async function load() {
      setError("");
      try {
        const run = await api<RunDetail>(`runs/${sourceRunId}`);
        if (run.workflow_id.startsWith("emulator-system-")) throw new Error(t("Cette opération d’appareil ne peut pas être modifiée ici."));
        const workflow = await api<Workflow>(`workflows/${encodeURIComponent(run.workflow_id)}/versions/${run.workflow_version}`);
        if (active) setSource({ run, workflow });
      } catch (failure) {
        if (active) setError((failure as Error).message);
      }
    }
    void load();
    return () => { active = false; };
  }, [sourceRunId, attempt, t]);

  if (sourceRunId && !source) {
    return <div className="surface run-authoring-load">
      {error ? <><ErrorNotice message={error} /><button type="button" className="button button--secondary" onClick={() => setAttempt(value => value + 1)}>{t("Réessayer")}</button></>
        : <p role="status">{t("Chargement de l’exécution…")}</p>}
    </div>;
  }
  const ids = source?.run.device_ids ?? [];
  const deviceId = ids.length === 1 && devices.some(device => device.device_id === ids[0]) ? ids[0] : undefined;
  return <RecipeEditor onClose={() => router.push("/activite")} run={{
    source: source?.workflow,
    sourceRunId,
    deviceId,
    onPrepared: workflow => onPrepared(workflow, source?.run)
  }} />;
}
