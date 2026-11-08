import type { Execution, Step } from "./console-types";

export type GalleryState = "pending" | "succeeded" | "skipped" | "failed" | "not-run" | "unconfirmed";
export type AndroidVersionResult = {
  type: "android_version";
  value: string;
  sdk_int: number;
  source: "android_system_properties";
};
export type GalleryStep = {
  id: string;
  label: string;
  state: GalleryState;
  captureUrl: string | null;
  capturedAt: string | null;
  durationMs: number | null;
  result: AndroidVersionResult | null;
};

const identifier = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const activeStates = new Set(["queued", "leased", "running", "recovering", "verifying_state", "waiting_auth"]);

function observedAndroidVersion(value: unknown): AndroidVersionResult | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const result = value as Record<string, unknown>;
  if (result.type !== "android_version" || result.source !== "android_system_properties"
    || typeof result.value !== "string" || !result.value.length || result.value.length > 64
    || result.value.trim() !== result.value || result.value.toLowerCase() === "unknown"
    || /[\u0000-\u001f\u007f-\u009f]/.test(result.value)
    || typeof result.sdk_int !== "number" || !Number.isInteger(result.sdk_int)
    || result.sdk_int < 1 || result.sdk_int > 10000) return null;
  return {type: "android_version", value: result.value, sdk_int: result.sdk_int, source: "android_system_properties"};
}

export function captureUrl(executionId: string, stepId: string): string | null {
  if (!uuid.test(executionId) || !identifier.test(stepId)) return null;
  return `/api/control/console/executions/${executionId}/captures/${encodeURIComponent(stepId)}`;
}

export function buildExecutionGallery(execution: Execution, steps?: Step[]): GalleryStep[] {
  const evidence: Record<string, unknown> = execution.evidence ?? {};
  const proofs = new Map<string, Record<string, unknown>>();
  for (const proof of Array.isArray(evidence.steps) ? evidence.steps : []) {
    if (proof && typeof proof === "object" && typeof proof.step_id === "string") proofs.set(proof.step_id, proof);
  }
  const failedId = typeof evidence.failed_step === "string" ? evidence.failed_step : null;
  const failedIndex = steps?.findIndex(step => step.id === failedId) ?? -1;
  const ordered = new Map<string, string>();
  for (const step of steps ?? []) {
    if (typeof step.id === "string" && step.id) ordered.set(step.id, typeof step.name === "string" && step.name.trim() ? step.name : step.id.replace(/[-_]/g, " "));
  }
  for (const id of [...proofs.keys(), ...(failedId ? [failedId] : [])]) {
    if (!ordered.has(id)) ordered.set(id, id.replace(/[-_]/g, " "));
  }
  return [...ordered].map(([id, label]) => {
    const proof = proofs.get(id);
    const state: GalleryState = id === failedId ? "failed"
      : proof?.skipped === true ? "skipped"
      : proof?.assertion_passed === true ? "succeeded"
      : proof ? "unconfirmed"
      : activeStates.has(execution.status) ? "pending"
      : execution.status === "failed" && failedIndex >= 0 && (steps?.findIndex(step => step.id === id) ?? -1) > failedIndex ? "not-run"
      : "unconfirmed";
    const capturedAt = typeof proof?.captured_at === "string" && /^\d{4}-\d{2}-\d{2}T/.test(proof.captured_at) && Number.isFinite(Date.parse(proof.captured_at)) ? proof.captured_at : null;
    const durationMs = typeof proof?.duration_ms === "number" && Number.isFinite(proof.duration_ms) && proof.duration_ms >= 0 ? proof.duration_ms : null;
    const result = state === "succeeded" ? observedAndroidVersion(proof?.result) : null;
    return { id, label, state, captureUrl: typeof proof?.screenshot === "string" && proof.screenshot.length > 0 ? captureUrl(execution.id, id) : null, capturedAt, durationMs, result };
  });
}

export function initialGallerySelection(steps: GalleryStep[], selectedId?: string | null): string | null {
  return steps.find(step => step.id === selectedId)?.id ?? steps.find(step => step.captureUrl)?.id ?? steps[0]?.id ?? null;
}
