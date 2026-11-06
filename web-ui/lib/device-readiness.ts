import type { Device } from "./console-types";

export function isDeviceReady(device: Device | undefined): boolean {
  return device?.connection_status === "connected" && device.availability !== "needs_review";
}

export function canSubmitDevices(ids: string[], devices: Device[], attempted = false): boolean {
  // An uncertain request must keep replaying its original key, even after disconnection.
  return attempted || (ids.length > 0 && ids.every(id => isDeviceReady(devices.find(device => device.device_id === id))));
}
