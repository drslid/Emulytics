export type RunSubmission = {
  workflow_id: string; workflow_version: number; device_ids: string[];
  max_concurrency: number; parameters: Record<string, never>; idempotency_key: string;
};
const identifier = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
export function parseRunDraft(value: unknown): RunSubmission | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  if (Object.keys(item).sort().join() !== ["workflow_id", "workflow_version", "device_ids", "max_concurrency", "parameters", "idempotency_key"].sort().join()) return null;
  if (typeof item.workflow_id !== "string" || !identifier.test(item.workflow_id)) return null;
  if (typeof item.workflow_version !== "number" || !Number.isInteger(item.workflow_version) || item.workflow_version < 1) return null;
  if (!Array.isArray(item.device_ids) || !item.device_ids.length || item.device_ids.length > 100 || item.device_ids.some((id) => typeof id !== "string" || !identifier.test(id)) || new Set(item.device_ids).size !== item.device_ids.length) return null;
  if (typeof item.max_concurrency !== "number" || !Number.isInteger(item.max_concurrency) || item.max_concurrency < 1 || item.max_concurrency > item.device_ids.length) return null;
  if (!item.parameters || typeof item.parameters !== "object" || Array.isArray(item.parameters) || Object.keys(item.parameters).length) return null;
  if (typeof item.idempotency_key !== "string" || !/^[a-f0-9-]{36}$/i.test(item.idempotency_key)) return null;
  return item as RunSubmission;
}
export function draftKey(userId: string) { return `emulytix:pending-run:${userId}`; }
