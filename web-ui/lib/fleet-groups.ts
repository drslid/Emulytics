import type { Device } from "./console-types";
export type FleetGroup = { id: string; name: string; revision: number; device_ids: string[] };
export type FleetGroupDetail = { group: FleetGroup; devices: Device[] };
export type FleetCapacity = { worker_slots: number; active_slots: number; available_slots: number; connected_devices: number; ready_devices: number; queued_executions: number; observed_at: string; hosts: { host_id: string; worker_slots: number; active_slots: number; available_slots: number; ready_devices: number }[] };
export type BulkAction = "start" | "prepare" | "stop";
export type BulkIntent = { request_id: string; action: BulkAction; device_ids: string[] };
export type BulkResult = { request_id: string; action: BulkAction; items: { device_id: string; status: "accepted" | "rejected"; run_id?: string; detail?: string }[] };
const identifier = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
export function bulkIntentKey(userId: string): string { return `emulytix-fleet-bulk:${userId}`; }
export function parseBulkIntent(value: unknown): BulkIntent | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const input = value as Record<string, unknown>;
  return Object.keys(input).length === 3 && typeof input.request_id === "string" && uuid.test(input.request_id) &&
    ["start", "prepare", "stop"].includes(String(input.action)) && Array.isArray(input.device_ids) &&
    input.device_ids.length > 0 && input.device_ids.length <= 100 && input.device_ids.every(id => typeof id === "string" && identifier.test(id)) &&
    new Set(input.device_ids).size === input.device_ids.length ? { request_id: input.request_id, action: input.action as BulkAction, device_ids: [...input.device_ids] } : null;
}
export function managedBulkTargets(ids: string[], managedIds: string[]): string[] {
  const managed = new Set(managedIds);
  return [...new Set(ids)].filter(id => managed.has(id)).sort();
}
