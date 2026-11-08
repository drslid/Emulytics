import type { Device } from "./console-types";

export function connectionWorkerHosts(devices: Device[], advertisedHosts?: string[]): string[] {
  const hosts = advertisedHosts ?? devices.filter(device => device.connection_status && device.connection_status !== "worker_offline").map(device => device.host_id);
  return [...new Set(hosts)].sort();
}

export function isDeviceReady(device: Device | undefined): boolean {
  return device?.connection_status === "connected" && device.availability !== "needs_review" && (!device.emulator_state || device.emulator_state === "ready");
}

export function canSubmitDevices(ids: string[], devices: Device[], attempted = false): boolean {
  // An uncertain request must keep replaying its original key, even after disconnection.
  return attempted || (ids.length > 0 && ids.every(id => isDeviceReady(devices.find(device => device.device_id === id))));
}
