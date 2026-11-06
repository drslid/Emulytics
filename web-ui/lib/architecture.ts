import { signalIsFresh, type MonitorSnapshot } from "./monitoring.ts";

export type ArchitectureNodeId = "web" | "api" | "api-go" | "database" | "scheduler" | "workers" | "android" | "artifacts";
export type ArchitectureState = "active" | "ready" | "warning" | "unknown";
export type ArchitectureEvent = keyof NonNullable<MonitorSnapshot["topology"]>["events"];
export type ArchitectureNode = { id: ArchitectureNodeId; label: string; state: ArchitectureState; confirmed: boolean };
export type ArchitectureEdge = {
  id: string; from: ArchitectureNodeId; to: ArchitectureNodeId; label: string; state: ArchitectureState;
  evidence: "recent" | "execution" | "stream" | "availability"; event?: ArchitectureEvent;
};

export function hasRecentActivity(data: MonitorSnapshot, key: ArchitectureEvent, elapsed: number): boolean {
  const topology = data.topology, event = topology?.events[key];
  if (!topology || !event || !Number.isFinite(event.count) || event.count <= 0 || !event.last_at || !Number.isFinite(elapsed) || elapsed < 0) return false;
  const observed = Date.parse(data.observed_at), occurred = Date.parse(event.last_at);
  if (!Number.isFinite(observed) || !Number.isFinite(occurred) || occurred > observed) return false;
  const age = (observed - occurred) / 1000 + elapsed + (topology.sample_age_seconds ?? 0);
  return Number.isFinite(age) && age >= 0 && age < topology.window_seconds;
}

export function buildArchitecture(data: MonitorSnapshot, live: boolean, elapsed: number) {
  const observationElapsed = elapsed + (data.topology?.sample_age_seconds ?? 0);
  const nodes: ArchitectureNode[] = [];
  function add(id: ArchitectureNodeId, label: string, confirmed: boolean, warning = false, active = false) {
    nodes.push({ id, label, confirmed: live && confirmed,
      state: !live ? "unknown" : warning ? "warning" : confirmed ? active ? "active" : "ready" : "unknown" });
  }
  function service(component: string) {
    const instances = data.services.filter(item => item.component === component);
    const confirmed = instances.some(item => signalIsFresh(item, observationElapsed, data.freshness.stale_after_seconds));
    return { confirmed, warning: !confirmed && instances.some(item => !!item.last_seen_at) };
  }
  const python = service("api"), go = service("api-go"), scheduler = service("scheduler"), workers = service("worker");
  const recent = (key: ArchitectureEvent) => hasRecentActivity(data, key, elapsed);
  const validFor = data.topology?.confirmed_device_executions_valid_for_seconds;
  const confirmedDeviceWork = typeof validFor === 'number' && Number.isFinite(validFor) && observationElapsed < validFor
    ? data.topology?.confirmed_device_executions ?? 0 : 0;
  const busyWorker = data.services.some(item => item.component === 'worker' && item.active_executions > 0 &&
    signalIsFresh(item, observationElapsed, data.freshness.stale_after_seconds));
  add("web", "Interface web", data.web.status === "ready", data.web.status === "unavailable");
  add("api", "API de contrôle", python.confirmed, python.warning, recent("console_commands"));
  add("api-go", "API Go", go.confirmed, go.warning);
  add("database", "PostgreSQL", data.database.status === "ready", data.database.status === "unavailable");
  add("scheduler", "Ordonnanceur", scheduler.confirmed, scheduler.warning || data.schedule_health.overdue > 0 || data.schedule_health.errors > 0, recent("scheduled_runs"));
  add("workers", "Workers Android", workers.confirmed, workers.warning || data.capacity.unconfirmed_leases > 0 || (!workers.confirmed && data.queue.queued > 0), workers.confirmed && (confirmedDeviceWork > 0 || busyWorker));
  add("android", "Appareils Android", data.fleet.connected > 0, data.fleet.needs_review > 0 || (data.fleet.total > 0 && data.fleet.connected === 0 && data.fleet.worker_offline + data.fleet.offline + data.fleet.unauthorized > 0), confirmedDeviceWork > 0 && workers.confirmed);
  add("artifacts", "Captures et preuves", data.topology?.storage.status === "readable", data.topology?.storage.status === "unavailable", recent("captures_published"));
  const byId = new Map(nodes.map(item => [item.id, item]));
  const edges: ArchitectureEdge[] = [];
  function edge(from: ArchitectureNodeId, to: ArchitectureNodeId, label: string,
                evidence: ArchitectureEdge["evidence"] = "availability", active = false, event?: ArchitectureEvent) {
    const start = byId.get(from)!, end = byId.get(to)!;
    const state = !live ? "unknown" : start.confirmed && end.confirmed ? active ? "active" : "ready"
      : start.state === "warning" || end.state === "warning" ? "warning" : "unknown";
    edges.push({ id: `${from}-${to}`, from, to, label, state, evidence, ...(event ? { event } : {}) });
  }
  edge("web", "api", "Commandes et sessions", "recent", recent("console_commands"), "console_commands");
  edge("api", "web", "Mesures en direct", "stream", live);
  edge("web", "api-go", "Lectures du tableau de bord");
  edge("api-go", "api", "Vérification des sessions");
  edge("api-go", "database", "Lectures PostgreSQL");
  edge("api", "database", "État et commandes", "recent", recent("console_commands"), "console_commands");
  edge("scheduler", "database", "Planifications", "recent", recent("scheduled_runs"), "scheduled_runs");
  edge("database", "workers", "File et réservations", confirmedDeviceWork > 0 ? "execution" : "recent",
    confirmedDeviceWork > 0 || recent("executions_started"), "executions_started");
  edge("workers", "android", "Exécution en cours", "execution", confirmedDeviceWork > 0);
  edge("workers", "artifacts", "Publication des captures", "recent", recent("captures_published"), "captures_published");
  edge("artifacts", "api", "Images privées");
  return { nodes, edges, windowSeconds: data.topology?.window_seconds ?? 15,
    sampled: !!data.topology && (data.topology.sampling.events_truncated || data.topology.sampling.captures_truncated) };
}
