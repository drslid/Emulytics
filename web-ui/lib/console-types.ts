export type User = { id: string; username: string };
export type View = "overview" | "devices" | "workflows" | "activity" | "security";
export type Device = {
  device_id: string; host_id: string; serial: string; kind: "physical" | "emulator";
  status: "registered"; created_at: string;
  availability: "declared" | "busy" | "needs_review";
  active_run_id: string | null; lease_expires_at: string | null;
};
export type Workflow = {
  workflow_id: string; version: number; recovery_budget: number; created_at: string;
  steps: { id: string; action: string }[];
};
export type Run = {
  id: string; workflow_id: string; workflow_version: number; device_ids: string[];
  max_concurrency: number; status: string; cancel_requested: boolean;
  created_at: string; updated_at: string;
};
export type Execution = {
  id: string; device_id: string; status: string; attempt: number; error: string | null;
  evidence: { steps?: { step_id: string; [key: string]: unknown }[] };
  lease_epoch: number | null;
};
export type RunDetail = Run & { run_id: string; executions: Execution[] };
export type RunEvent = { sequence: number; type: string; created_at: string; payload: Record<string, unknown> };
export type Summary = {
  devices_total: number; runs_total: number; runs_active: number;
  runs_needs_review: number; runs_succeeded: number; workflows_total: number;
};
export type Data = { devices: Device[]; devicesTotal: number; workflows: Workflow[]; runs: Run[]; summary: Summary };
export type Page<T> = { items: T[]; limit: number; offset: number; total?: number };
