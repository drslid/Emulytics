import { parseRunDraft } from "./run-draft.ts";

export type ScheduleSubmission = {
  request_id: string; name: string; workflow_id: string; workflow_version: number;
  device_ids: string[]; max_concurrency: number; cron: string; timezone: string; enabled: true;
};

/** A persisted request is replayed verbatim; only the API interprets CRON and timezone rules. */
export function parseScheduleDraft(value: unknown): ScheduleSubmission | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  const keys = ["request_id", "name", "workflow_id", "workflow_version", "device_ids", "max_concurrency", "cron", "timezone", "enabled"];
  if (Object.keys(item).sort().join() !== keys.sort().join() || item.enabled !== true) return null;
  if (typeof item.name !== "string" || !item.name.trim() || item.name.length > 120 ||
      typeof item.cron !== "string" || !item.cron.trim() || item.cron.length > 120 ||
      typeof item.timezone !== "string" || !item.timezone.trim() || item.timezone.length > 100 ||
      typeof item.request_id !== "string" || !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(item.request_id)) return null;
  if (!parseRunDraft({ workflow_id: item.workflow_id, workflow_version: item.workflow_version,
    device_ids: item.device_ids, max_concurrency: item.max_concurrency, parameters: {}, idempotency_key: item.request_id })) return null;
  return item as ScheduleSubmission;
}

export function scheduleDraftKey(userId: string) { return `emulytix:pending-schedule:${userId}`; }
