export type EmulatorApplication = { id: string; name: string; package_name: string; source: "system" | "apk"; size_bytes: number; available: boolean };
export type ManagedEmulator = {
  id: string; device_id: string; display_name: string; host_id: string; serial: string;
  state: "created" | "starting" | "running" | "ready" | "stopped" | "preparing" | "failed" | "unknown";
  application_ids: string[]; installed_packages: string[]; last_error: string | null; last_run_id: string | null;
  operation_status: string | null; availability: "declared" | "busy" | "needs_review"; updated_at: string;
  device?: Device;
  hardware?: EmulatorHardware; applied_hardware?: AppliedEmulatorHardware | null; storage_editable?: boolean;
};
export type EmulatorCatalog = { items: ManagedEmulator[]; applications: EmulatorApplication[]; hosts: string[]; enabled: boolean; max_per_host: number };
export type EmulatorAction = "start" | "prepare" | "stop";
export type EmulatorOperation = { action: EmulatorAction; idempotency_key: string };
export type EmulatorCreation = { name: string; host_id: string; application_ids: string[]; idempotency_key: string; hardware?: EmulatorHardware };
export const MAX_APK_BYTES = 128 * 1024 * 1024;

const active = new Set(["queued", "leased", "running", "recovering", "verifying_state", "waiting_auth"]);
const identifier = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;

export function emulatorOperationActive(emulator: ManagedEmulator): boolean {
  return emulator.state === "starting" || emulator.state === "preparing" || active.has(emulator.operation_status ?? "");
}
export function emulatorCanManage(emulator: ManagedEmulator, action: EmulatorAction, applications: EmulatorApplication[] = []): boolean {
  if (emulator.availability !== "declared" || emulatorOperationActive(emulator)) return false;
  if (action === "stop") return !["created", "stopped"].includes(emulator.state);
  if (action === "start") return !["running", "ready"].includes(emulator.state);
  return missingEmulatorApplications(emulator.application_ids, applications).length === 0;
}
export function emulatorCanLaunch(emulator: ManagedEmulator, deviceReady: boolean): boolean {
  return emulator.state === "ready" && !emulatorOperationActive(emulator) && emulator.availability !== "needs_review" && deviceReady;
}
export function missingEmulatorApplications(ids: string[], applications: EmulatorApplication[]): string[] {
  return ids.filter(id => !applications.some(application => application.id === id && application.available));
}
export function canonicalizeEmulatorUpload(uploaded: EmulatorApplication, applications: EmulatorApplication[], selected: string[]): { application: EmulatorApplication; selected: string[] } {
  const preset = applications.find(application => application.source === "apk" && application.package_name === uploaded.package_name && !uuid.test(application.id));
  const application = preset ? { ...uploaded, id: preset.id, name: preset.name, available: true } : uploaded;
  const samePackage = new Set([uploaded.id, application.id, ...applications.filter(item => item.package_name === uploaded.package_name).map(item => item.id)]);
  const next: string[] = [];
  let included = false;
  for (const id of selected) {
    if (!samePackage.has(id)) next.push(id);
    else if (!included) { next.push(application.id); included = true; }
  }
  if (!included && next.length < 12) next.push(application.id);
  return { application, selected: next };
}
export function emulatorConnectionDevice(emulator: ManagedEmulator, devices: Device[]): Device | undefined {
  return emulator.device?.device_id === emulator.device_id ? emulator.device : devices.find(device => device.device_id === emulator.device_id);
}
export function currentEmulatorLaunchDevice(selected: Device | undefined, devices: Device[]): Device | undefined {
  return selected ? devices.find(device => device.device_id === selected.device_id) ?? { ...selected, connection_status: "unknown" } : undefined;
}
export function mergeEmulatorLaunchDevices(devices: Device[], selected?: Device): Device[] {
  const unique = new Map(devices.map(device => [device.device_id, device]));
  if (!selected) return [...unique.values()];
  const current = unique.get(selected.device_id);
  if (!current) return [selected, ...unique.values()];
  const observed = (device: Device) => Date.parse(device.worker_last_seen_at ?? "") || 0;
  if (observed(selected) > observed(current)) unique.set(selected.device_id, selected);
  return [...unique.values()];
}
export function emulatorIntentKey(userId: string, deviceId = "create"): string { return `emulytix-emulator:${userId}:${deviceId}`; }
function object(value: unknown): Record<string, unknown> { return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
export function parseEmulatorOperation(value: unknown): EmulatorOperation | null {
  const input = object(value);
  return ["start", "prepare", "stop"].includes(String(input.action)) && typeof input.idempotency_key === "string" && uuid.test(input.idempotency_key) ? { action: input.action as EmulatorAction, idempotency_key: input.idempotency_key } : null;
}
export function parseEmulatorCreation(value: unknown): EmulatorCreation | null {
  const input = object(value);
  const hardware = input.hardware === undefined ? undefined : parseHardware(input.hardware);
  return typeof input.name === "string" && input.name.trim().length > 0 && input.name.length <= 160 &&
    typeof input.host_id === "string" && identifier.test(input.host_id) && typeof input.idempotency_key === "string" && uuid.test(input.idempotency_key) &&
    Array.isArray(input.application_ids) && input.application_ids.length <= 12 && input.application_ids.every(id => typeof id === "string" && identifier.test(id)) && new Set(input.application_ids).size === input.application_ids.length && hardware !== null
    ? { name: input.name, host_id: input.host_id, application_ids: input.application_ids, idempotency_key: input.idempotency_key, ...(hardware ? { hardware } : {}) } : null;
}
import type { Device } from "./console-types";
import { parseHardware, type AppliedEmulatorHardware, type EmulatorHardware } from "./emulator-hardware.ts";

