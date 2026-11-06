export type MonitorWindow = "1h" | "24h" | "7d";
export type ServiceSignal = {
  component: string;
  instance_id: string;
  host_id: string | null;
  status: string;
  live: boolean;
  age_seconds: number | null;
  last_seen_at: string | null;
  active_executions: number;
  metrics: {
    adb_status?: string;
    resources?: {
      scope: "process";
      cpu_cores: number | null;
      memory_rss_bytes: number | null;
      uptime_seconds: number;
      sample_interval_seconds: number | null;
      observed_at: string;
    };
  };
};
export type MonitorSnapshot = {
  observed_at: string;
  freshness: { heartbeat_interval_seconds: number; stale_after_seconds: number };
  database: { status: string; latency_ms: number; connections_used?: number | null; connections_max?: number | null; size_bytes?: number | null };
  web: { status: string };
  services: ServiceSignal[];
  capacity: { live_workers: number; busy_workers: number; idle_workers: number; utilization_percent: number | null; unconfirmed_leases: number };
  queue: { queued: number; oldest_created_at: string | null; oldest_age_seconds: number | null; active: number; waiting_auth: number };
  fleet: { total: number; connected: number; ready: number; busy: number; needs_review: number; unauthorized: number; offline: number; not_connected: number; worker_offline: number; unknown: number };
  results: {
    window: MonitorWindow; window_seconds: number; sample_size: number; sample_limit: number; truncated: boolean;
    succeeded: number; failed: number; cancelled: number; needs_review: number; success_percent: number | null;
    duration_p50_seconds: number | null; duration_p95_seconds: number | null; duration_sample_size: number;
    queue_wait_p95_seconds: number | null; queue_wait_sample_size: number; last_success_at: string | null;
  };
  hosts: { host_id: string; devices: number; live_workers: number; busy_workers: number; connected_devices: number; ready_devices: number; queued: number }[];
  leases: { active: number; needs_review: number };
  schedules: { enabled: number; next_run_at: string | null };
  schedule_health: { overdue: number; errors: number; oldest_overdue_seconds: number | null };
  topology?: {
    window_seconds: number;
    sample_age_seconds: number;
    events: Record<"console_commands" | "scheduled_runs" | "executions_started" | "actions_completed" | "steps_published" | "captures_published", { count: number; last_at: string | null }>;
    sampling: { limit: number; events_truncated: boolean; captures_truncated: boolean };
    storage: { status: "readable" | "unavailable" | "unconfigured" };
    confirmed_device_executions: number;
    confirmed_device_executions_valid_for_seconds: number | null;
  };
};

export function topologyIsValid(value: unknown): boolean {
  if (value === undefined) return true;
  if (!value || typeof value !== 'object') return false;
  const topology = value as NonNullable<MonitorSnapshot['topology']>;
  const events = topology.events, sampling = topology.sampling;
  return topology.window_seconds === 15 && Number.isFinite(topology.sample_age_seconds) && topology.sample_age_seconds >= 0 &&
    Number.isSafeInteger(topology.confirmed_device_executions) &&
    topology.confirmed_device_executions >= 0 &&
    (topology.confirmed_device_executions === 0 ? topology.confirmed_device_executions_valid_for_seconds === null :
      typeof topology.confirmed_device_executions_valid_for_seconds === 'number' && Number.isFinite(topology.confirmed_device_executions_valid_for_seconds) &&
      topology.confirmed_device_executions_valid_for_seconds > 0 && topology.confirmed_device_executions_valid_for_seconds <= 20) &&
    !!sampling && sampling.limit === 1000 &&
    typeof sampling.events_truncated === 'boolean' && typeof sampling.captures_truncated === 'boolean' &&
    !!topology.storage && ['readable','unavailable','unconfigured'].includes(topology.storage.status) &&
    !!events && ['console_commands','scheduled_runs','executions_started','actions_completed','steps_published','captures_published'].every(key => {
      const event = events[key as keyof typeof events];
      return !!event && Number.isSafeInteger(event.count) && event.count >= 0 &&
        (event.last_at === null || typeof event.last_at === 'string' && Number.isFinite(Date.parse(event.last_at)));
    });
}

export function streamIsFresh(receivedAt: number | null, now: number): boolean {
  return receivedAt !== null && Number.isFinite(receivedAt) && Number.isFinite(now) && now >= receivedAt && now - receivedAt <= 10_000;
}

export function signalIsFresh(signal: ServiceSignal, elapsedSeconds: number, staleAfter: number): boolean {
  return signal.live && signal.status === "ready" && signal.age_seconds !== null && Number.isFinite(signal.age_seconds) &&
    signal.age_seconds >= 0 && signal.age_seconds + elapsedSeconds < staleAfter;
}

export function currentSignals(services: ServiceSignal[]): ServiceSignal[] {
  const current: ServiceSignal[] = [];
  for (const component of new Set(services.map((service) => service.component))) {
    const instances = services.filter((service) => service.component === component);
    const live = instances.filter((service) => service.live);
    if (live.length) current.push(...live);
    else current.push([...instances].sort((a, b) => (b.last_seen_at ?? "").localeCompare(a.last_seen_at ?? ""))[0]);
  }
  return current;
}
