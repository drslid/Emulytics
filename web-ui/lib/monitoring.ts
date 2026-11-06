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
};

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
