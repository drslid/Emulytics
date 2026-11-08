export type User = {
  id: string;
  username: string;
  display_name: string;
  first_name: string;
  last_name: string;
  email: string | null;
  role: "admin" | "builder" | "operator" | "viewer" | "auditor";
  permissions: string[];
  active: boolean;
};
export type View =
  | "overview"
  | "devices"
  | "workflows"
  | "activity"
  | "schedules"
  | "users"
  | "monitor"
  | "logs"
  | "configuration"
  | "profile";
export type Device = {
  device_id: string;
  display_name: string;
  host_id: string;
  serial: string;
  kind: "physical" | "emulator";
  status: "registered";
  created_at: string;
  availability: "declared" | "busy" | "needs_review";
  emulator_state?: string | null;
  connection_status?:
    | "connected"
    | "worker_offline"
    | "not_connected"
    | "unauthorized"
    | "offline"
    | "unknown";
  worker_last_seen_at?: string | null;
  active_run_id: string | null;
  lease_expires_at: string | null;
};
export type Workflow = {
  workflow_id: string;
  version: number;
  recovery_budget: number;
  created_at: string;
  steps: Step[];
  name?: string;
  instructions?: string;
};
export type Run = {
  id: string;
  workflow_id: string;
  workflow_version: number;
  device_ids: string[];
  max_concurrency: number;
  status: string;
  cancel_requested: boolean;
  created_at: string;
  updated_at: string;
};
export type Execution = {
  id: string;
  device_id: string;
  status: string;
  attempt: number;
  error: string | null;
  evidence: {
    steps?: {
      step_id: string;
      assertion_passed?: boolean;
      skipped?: boolean;
      screenshot?: string;
      captured_at?: string;
      duration_ms?: number;
      [key: string]: unknown;
    }[];
    failed_step?: string | null;
  };
  lease_epoch: number | null;
};
export type RunDetail = Run & { run_id: string; executions: Execution[] };
export type RunEvent = {
  sequence: number;
  type: string;
  created_at: string;
  payload: Record<string, unknown>;
};
export type Summary = {
  devices_total: number;
  runs_total: number;
  runs_active: number;
  runs_needs_review: number;
  runs_succeeded: number;
  workflows_total: number;
};
export type Data = {
  devices: Device[];
  devicesTotal: number;
  workerHosts: string[];
  workflows: Workflow[];
  runs: Run[];
  summary: Summary;
};
export type Page<T> = {
  items: T[];
  limit: number;
  offset: number;
  total?: number;
};

export type Step = {
  id: string;
  action: string;
  args?: Record<string, unknown>;
  selectors?: Record<string, unknown>[];
  assert?: Record<string, unknown>;
  timeout_ms?: number;
  non_idempotent?: boolean;
  verify_after_crash?: Record<string, unknown>;
  [key: string]: unknown;
};
export type Recipe = {
  id: string;
  workflow_id: string;
  revision: number;
  latest_version: number | null;
  status: "draft" | "published";
  name: string;
  instructions: string;
  definition: { steps: Step[]; recovery_budget: number };
};
export type Schedule = {
  id: string;
  name: string;
  workflow_id: string;
  workflow_version: number;
  device_ids: string[];
  max_concurrency: number;
  cron: string;
  timezone: string;
  enabled: boolean;
  next_run_at: string;
  last_run_id: string | null;
  last_error: string | null;
};
