export type EmulatorHardware = { width: number; height: number; density: number; ram_mb: number; cpu_cores: number; storage_gb: number };
export type AppliedEmulatorHardware = Omit<EmulatorHardware,"storage_gb"> & { storage_capacity_bytes?: number | null };
export const DEFAULT_HARDWARE: EmulatorHardware = { width: 720, height: 1280, density: 320, ram_mb: 1536, cpu_cores: 2, storage_gb: 8 };
export const hardwarePresets = {
  compact: DEFAULT_HARDWARE,
  balanced: { width: 1080, height: 1920, density: 420, ram_mb: 2048, cpu_cores: 2, storage_gb: 16 },
  tablet: { width: 1280, height: 800, density: 160, ram_mb: 3072, cpu_cores: 4, storage_gb: 16 },
} satisfies Record<string, EmulatorHardware>;
const keys = Object.keys(DEFAULT_HARDWARE) as (keyof EmulatorHardware)[];
export function parseHardware(value: unknown): EmulatorHardware | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const input = value as Record<string, unknown>;
  if (Object.keys(input).length !== keys.length || keys.some(key => !Number.isInteger(input[key]))) return null;
  const h = input as EmulatorHardware;
  return h.width >= 320 && h.width <= 2560 && h.height >= 320 && h.height <= 3200 &&
    h.width % 8 === 0 && h.height % 8 === 0 && h.width * h.height <= 4194304 &&
    Math.max(h.width, h.height) <= Math.min(h.width, h.height) * 3.2 &&
    h.density >= 120 && h.density <= 640 && h.ram_mb >= 1024 && h.ram_mb <= 8192 && h.ram_mb % 256 === 0 &&
    h.cpu_cores >= 1 && h.cpu_cores <= 8 && h.storage_gb >= 2 && h.storage_gb <= 64 ? { ...h } : null;
}
export function sameHardware(left: EmulatorHardware, right: EmulatorHardware): boolean {
  return keys.every(key => left[key] === right[key]);
}
export function sameAppliedHardware(configured: EmulatorHardware, applied: AppliedEmulatorHardware): boolean {
  return keys.filter(key=>key!=="storage_gb").every(key=>configured[key]===applied[key as keyof AppliedEmulatorHardware]);
}
export function hardwareEditable(emulator: { state: string; availability: string; operation_status: string | null }): boolean {
  return ["created", "stopped"].includes(emulator.state) && emulator.availability === "declared" &&
    !["queued", "leased", "running", "recovering", "verifying_state", "waiting_auth"].includes(emulator.operation_status ?? "");
}
